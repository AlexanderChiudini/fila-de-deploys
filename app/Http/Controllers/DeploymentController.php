<?php

namespace App\Http\Controllers;

use App\GoogleChatNotifier;
use App\Models\Deployment;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;

class DeploymentController extends Controller
{
    private const STATUSES = ['aguardando', 'em andamento', 'finalizado'];

    public function index(): JsonResponse
    {
        return response()->json(Deployment::orderBy('position')->orderBy('id')->get());
    }

    public function destroy(Deployment $deployment): JsonResponse
    {
        $deployment->delete();

        return response()->json(['deleted' => 1]);
    }

    public function move(Request $request, Deployment $deployment): JsonResponse
    {
        $data = $request->validate([
            'direction' => ['required', Rule::in(['up', 'down', 'end'])],
        ]);

        $records = DB::transaction(function () use ($deployment, $data) {
            $records = Deployment::orderBy('position')->orderBy('id')->lockForUpdate()->get();
            $index = $records->search(fn (Deployment $record): bool => $record->id === $deployment->id);
            abort_if($index === false, 404);
            $target = match ($data['direction']) {
                'up' => max(0, $index - 1),
                'down' => min($records->count() - 1, $index + 1),
                'end' => $records->count() - 1,
            };
            $ordered = $records->all();
            $moved = array_splice($ordered, $index, 1);
            array_splice($ordered, $target, 0, $moved);
            foreach ($ordered as $offset => $record) {
                $record->position = $offset + 1;
                $record->save();
            }

            return $ordered;
        }, 5);

        return response()->json($records);
    }

    public function clearFinished(): JsonResponse
    {
        $deleted = Deployment::where('status', 'finalizado')->delete();

        return response()->json(['deleted' => $deleted]);
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'responsible' => ['required', 'string', 'max:100'],
            'squad' => ['required', 'string', 'max:100'],
            'url' => ['required', 'url:http,https', 'max:2048'],
            'status' => ['sometimes', 'required', Rule::in(self::STATUSES)],
            'notes' => ['nullable', 'string', 'max:2000'],
        ]);

        $deployment = DB::transaction(function () use ($data): Deployment {
            $records = Deployment::orderBy('position')->orderBy('id')->lockForUpdate()->get();
            $deployment = new Deployment($data + ['status' => 'aguardando']);
            $deployment->position = ($records->max('position') ?? 0) + 1;
            $deployment->save();

            return $deployment;
        }, 5);

        return response()->json($deployment, 201);
    }

    public function update(Request $request, Deployment $deployment, GoogleChatNotifier $notifier): JsonResponse
    {
        $data = $request->validate([
            'status' => ['sometimes', 'required', Rule::in(self::STATUSES)],
            'notes' => ['sometimes', 'nullable', 'string', 'max:2000'],
        ]);
        [$deployment, $finished] = DB::transaction(function () use ($deployment, $data): array {
            $record = Deployment::whereKey($deployment->id)->lockForUpdate()->firstOrFail();
            $previousStatus = $record->status;
            $record->update($data);

            return [$record, $previousStatus !== 'finalizado' && $record->status === 'finalizado'];
        }, 5);

        if ($finished) {
            $notifier->sendFinished($deployment);
        }

        return response()->json($deployment->fresh());
    }
}
