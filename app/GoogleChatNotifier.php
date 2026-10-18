<?php

namespace App;

use App\Models\Deployment;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Throwable;

class GoogleChatNotifier
{
    public function sendFinished(Deployment $deployment): void
    {
        $url = config('services.google_chat.webhook_url');
        if (! config('services.google_chat.enabled') || ! $url) {
            return;
        }

        $text = implode("\n", [
            "Deploy #{$deployment->id} finalizado",
            "Responsável: {$deployment->responsible}",
            "Squad: {$deployment->squad}",
            "Link: {$deployment->url}",
            'Observação: '.($deployment->notes ?: 'Não informada'),
            'Fila: '.config('app.url'),
        ]);

        try {
            $response = Http::connectTimeout(2)->timeout(5)->withoutRedirecting()->post($url, ['text' => $text]);
            if (! $response->successful()) {
                Log::warning('Falha ao notificar deploy no Google Chat.', [
                    'deployment_id' => $deployment->id, 'http_status' => $response->status(),
                ]);
            }
        } catch (Throwable) {
            Log::warning('Não foi possível conectar ao Google Chat.', ['deployment_id' => $deployment->id]);
        }
    }
}
