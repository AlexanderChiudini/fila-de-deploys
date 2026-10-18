<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Tests\TestCase;

class GoogleChatNotificationTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        Http::preventStrayRequests();
        config(['services.google_chat.enabled' => true, 'services.google_chat.webhook_url' => 'https://chat.googleapis.com/v1/spaces/test/messages?key=fake&token=fake']);
    }

    public function test_only_a_transition_to_finished_sends_the_deployment_details(): void
    {
        Http::fake(['chat.googleapis.com/*' => Http::response([], 200)]);
        $id = $this->postJson('/api/deployments', [
            'responsible' => 'Ana', 'squad' => 'Plataforma', 'url' => 'https://example.com/deploy', 'notes' => 'Migration executada',
        ])->assertCreated()->json('id');
        $this->patchJson("/api/deployments/{$id}", ['status' => 'em andamento'])->assertOk();
        Http::assertNothingSent();
        $this->patchJson("/api/deployments/{$id}", ['status' => 'finalizado'])->assertOk();
        Http::assertSent(fn ($request) => $request->method() === 'POST'
            && $request->url() === config('services.google_chat.webhook_url')
            && str_contains($request['text'], "Deploy #{$id} finalizado")
            && str_contains($request['text'], 'Ana')
            && str_contains($request['text'], 'Plataforma')
            && str_contains($request['text'], 'https://example.com/deploy')
            && str_contains($request['text'], 'Migration executada'));
        $this->patchJson("/api/deployments/{$id}", ['status' => 'finalizado'])->assertOk();
        $this->patchJson("/api/deployments/{$id}", ['notes' => 'Outra observação'])->assertOk();
        $this->patchJson("/api/deployments/{$id}/move", ['direction' => 'end'])->assertOk();
        Http::assertSentCount(1);
        $this->patchJson("/api/deployments/{$id}", ['status' => 'aguardando'])->assertOk();
        $this->patchJson("/api/deployments/{$id}", ['status' => 'finalizado'])->assertOk();
        Http::assertSentCount(2);
    }

    public function test_disabled_or_unconfigured_notifications_do_not_send_requests(): void
    {
        Http::fake();
        foreach ([['enabled' => false, 'webhook_url' => 'https://example.com'], ['enabled' => true, 'webhook_url' => '']] as $settings) {
            config(['services.google_chat' => $settings]);
            $id = $this->postJson('/api/deployments', ['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com'])->json('id');
            $this->patchJson("/api/deployments/{$id}", ['status' => 'finalizado'])->assertOk();
        }
        Http::assertNothingSent();
    }

    public function test_http_failure_and_connection_failure_do_not_undo_the_status_change(): void
    {
        Log::spy();
        foreach ([Http::response([], 500), Http::failedConnection()] as $response) {
            Http::fake(['chat.googleapis.com/*' => $response]);
            $id = $this->postJson('/api/deployments', ['responsible' => 'Ana', 'squad' => 'Web', 'url' => 'https://example.com'])->json('id');
            $this->patchJson("/api/deployments/{$id}", ['status' => 'finalizado'])->assertOk()->assertJsonPath('status', 'finalizado');
            $this->assertDatabaseHas('deployments', ['id' => $id, 'status' => 'finalizado']);
        }
        Log::shouldHaveReceived('warning')->twice();
    }
}
