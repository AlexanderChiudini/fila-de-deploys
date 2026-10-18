<?php

namespace Tests\Feature;

use App\Models\Deployment;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class DeploymentTest extends TestCase
{
    use RefreshDatabase;

    public function test_records_can_move_up_down_and_to_the_end_with_order_persisted(): void
    {
        $ids = [];
        foreach (['aguardando', 'em andamento', 'finalizado'] as $status) {
            $ids[] = $this->postJson('/api/deployments', [
                'responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com',
                'status' => $status, 'notes' => 'Preservar observação',
            ])->assertCreated()->json('id');
        }
        $this->patchJson("/api/deployments/{$ids[1]}/move", ['direction' => 'up'])
            ->assertOk()->assertJsonPath('0.id', $ids[1])->assertJsonPath('1.id', $ids[0]);
        $this->getJson('/api/deployments')->assertJsonPath('0.id', $ids[1]);
        $this->patchJson("/api/deployments/{$ids[1]}/move", ['direction' => 'down'])
            ->assertOk()->assertJsonPath('0.id', $ids[0])->assertJsonPath('1.id', $ids[1]);
        $this->patchJson("/api/deployments/{$ids[0]}/move", ['direction' => 'end'])
            ->assertOk()->assertJsonPath('0.id', $ids[1])->assertJsonPath('1.id', $ids[2])->assertJsonPath('2.id', $ids[0]);
        $this->assertDatabaseHas('deployments', ['id' => $ids[0], 'position' => 3, 'status' => 'aguardando', 'notes' => 'Preservar observação']);
        $this->patchJson("/api/deployments/{$ids[1]}/move", ['direction' => 'up'])->assertOk()->assertJsonPath('0.id', $ids[1]);
        $this->patchJson("/api/deployments/{$ids[0]}/move", ['direction' => 'down'])->assertOk()->assertJsonPath('2.id', $ids[0]);
        $this->patchJson("/api/deployments/{$ids[0]}/move", ['direction' => 'end'])->assertOk()->assertJsonPath('2.id', $ids[0]);
        $this->patchJson("/api/deployments/{$ids[0]}/move", ['direction' => 'invalid'])->assertUnprocessable();
        $this->patchJson('/api/deployments/999999/move', ['direction' => 'up'])->assertNotFound();
        $newId = $this->postJson('/api/deployments', [
            'responsible' => 'Bia', 'squad' => 'API', 'url' => 'https://example.com/new',
        ])->assertCreated()->json('id');
        $this->getJson('/api/deployments')->assertJsonPath('3.id', $newId);
    }

    public function test_deleting_one_record_preserves_the_rest_and_reordering_still_works(): void
    {
        $ids = [];
        foreach (['aguardando', 'em andamento', 'finalizado'] as $status) {
            $ids[] = $this->postJson('/api/deployments', [
                'responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com', 'status' => $status,
            ])->assertCreated()->json('id');
        }
        $this->deleteJson("/api/deployments/{$ids[1]}")->assertOk()->assertExactJson(['deleted' => 1]);
        $this->assertDatabaseMissing('deployments', ['id' => $ids[1]]);
        $this->assertDatabaseCount('deployments', 2);
        $this->getJson('/api/deployments')->assertJsonPath('0.id', $ids[0])->assertJsonPath('1.id', $ids[2]);
        $this->patchJson("/api/deployments/{$ids[2]}/move", ['direction' => 'up'])
            ->assertOk()->assertJsonPath('0.id', $ids[2])->assertJsonPath('1.id', $ids[0]);
        $this->deleteJson("/api/deployments/{$ids[1]}")->assertNotFound();
        $this->deleteJson('/api/deployments/999999')->assertNotFound();
        $this->deleteJson('/api/deployments/finished')->assertOk()->assertExactJson(['deleted' => 1]);
        $this->deleteJson("/api/deployments/{$ids[0]}")->assertOk();
        $this->getJson('/api/deployments')->assertExactJson([]);
    }

    public function test_optional_notes_can_be_created_edited_and_cleared_without_changing_status(): void
    {
        $data = ['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com'];
        $this->postJson('/api/deployments', $data)->assertCreated()->assertJsonPath('notes', null);
        $id = $this->postJson('/api/deployments', $data + ['notes' => "Executar migration.\nAvisar o time."])
            ->assertCreated()->json('id');
        $this->assertDatabaseHas('deployments', ['id' => $id, 'notes' => "Executar migration.\nAvisar o time."]);
        $this->patchJson("/api/deployments/{$id}", ['notes' => 'Migration executada.'])
            ->assertOk()->assertJsonPath('notes', 'Migration executada.')->assertJsonPath('status', 'aguardando');
        $this->patchJson("/api/deployments/{$id}", ['status' => 'em andamento'])
            ->assertOk()->assertJsonPath('notes', 'Migration executada.');
        $this->getJson('/api/deployments')->assertOk()->assertJsonPath('1.notes', 'Migration executada.');
        $this->patchJson("/api/deployments/{$id}", ['notes' => ''])
            ->assertOk()->assertJsonPath('notes', null)->assertJsonPath('status', 'em andamento');
        $this->assertDatabaseHas('deployments', ['id' => $id, 'notes' => null]);
    }

    public function test_notes_must_be_text_with_at_most_2000_characters(): void
    {
        $data = ['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com'];
        $id = $this->postJson('/api/deployments', $data + ['notes' => str_repeat('a', 2000)])
            ->assertCreated()->json('id');
        foreach ([str_repeat('a', 2001), ['invalid']] as $notes) {
            $this->postJson('/api/deployments', $data + ['notes' => $notes])
                ->assertUnprocessable()->assertJsonValidationErrors('notes');
            $this->patchJson("/api/deployments/{$id}", ['notes' => $notes])
                ->assertUnprocessable()->assertJsonValidationErrors('notes');
        }
        $this->assertDatabaseHas('deployments', ['id' => $id, 'notes' => str_repeat('a', 2000)]);
    }

    public function test_clearing_finished_deployments_preserves_other_statuses(): void
    {
        $ids = [];
        foreach (['aguardando', 'em andamento', 'finalizado', 'finalizado'] as $status) {
            $ids[] = $this->postJson('/api/deployments', [
                'responsible' => 'Ana', 'squad' => 'Web',
                'url' => 'https://example.com', 'status' => $status,
            ])->assertCreated()->json('id');
        }

        $this->deleteJson('/api/deployments/finished')->assertOk()->assertExactJson(['deleted' => 2]);
        $this->assertDatabaseCount('deployments', 2);
        $this->assertDatabaseHas('deployments', ['id' => $ids[0], 'status' => 'aguardando']);
        $this->assertDatabaseHas('deployments', ['id' => $ids[1], 'status' => 'em andamento']);
        $this->assertDatabaseMissing('deployments', ['id' => $ids[2]]);
        $this->assertDatabaseMissing('deployments', ['id' => $ids[3]]);
        $this->getJson('/api/deployments')->assertOk()->assertJsonCount(2);
        $this->deleteJson('/api/deployments/finished')->assertOk()->assertExactJson(['deleted' => 0]);
        $this->assertDatabaseCount('deployments', 2);
    }

    public function test_anyone_can_create_list_and_update_a_deployment(): void
    {
        $data = ['responsible' => 'Ana', 'squad' => 'Plataforma', 'url' => 'https://github.com/team/app/actions/runs/1'];
        $id = $this->postJson('/api/deployments', $data)->assertCreated()->assertJsonPath('status', 'aguardando')->json('id');
        $this->getJson('/api/deployments')->assertOk()->assertJsonPath('0.id', $id);
        foreach (['em andamento', 'finalizado', 'aguardando'] as $status) {
            $this->patchJson("/api/deployments/{$id}", ['status' => $status])->assertOk()->assertJsonPath('status', $status);
            $this->assertDatabaseHas('deployments', ['id' => $id, 'status' => $status]);
        }
    }

    public function test_invalid_records_and_statuses_are_rejected(): void
    {
        $this->postJson('/api/deployments', [])->assertUnprocessable()->assertJsonValidationErrors(['responsible', 'squad', 'url']);
        $data = ['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'javascript:alert(1)'];
        $this->postJson('/api/deployments', $data)->assertUnprocessable()->assertJsonValidationErrors('url');
        $data['url'] = 'https://example.com';
        $data['status'] = 'cancelado';
        $this->postJson('/api/deployments', $data)->assertUnprocessable()->assertJsonValidationErrors('status');
        unset($data['status']);
        $id = $this->postJson('/api/deployments', $data)->json('id');
        $this->patchJson("/api/deployments/{$id}", ['status' => 'cancelado'])->assertUnprocessable();
        $this->assertDatabaseHas('deployments', ['id' => $id, 'status' => 'aguardando']);
        $this->patchJson('/api/deployments/999999', ['status' => 'finalizado'])->assertNotFound();
    }

    public function test_records_are_in_creation_order_and_status_updates_cannot_change_owner(): void
    {
        $first = Deployment::create(['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com', 'status' => 'aguardando']);
        $second = Deployment::create(['responsible' => 'Bia', 'squad' => 'API', 'url' => 'https://example.com/2', 'status' => 'finalizado']);
        $this->patchJson("/api/deployments/{$first->id}", ['status' => 'em andamento', 'responsible' => 'Outra pessoa'])->assertOk()->assertJsonPath('responsible', 'Ana');
        $this->getJson('/api/deployments')->assertJsonPath('0.id', $first->id)->assertJsonPath('1.id', $second->id);
    }
}
