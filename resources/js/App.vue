<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';

const deployments = ref([]);
const loading = ref(true);
const saving = ref(false);
const clearing = ref(false);
const updating = reactive(new Set());
const error = ref('');
const notice = ref('');
const search = ref('');
const filter = ref('todos');
const fieldErrors = ref({});
const editingNotes = ref(null);
const notesDraft = ref('');
const notesError = ref('');
const statuses = ['aguardando', 'em andamento', 'finalizado'];
const labels = { aguardando: 'Aguardando', 'em andamento': 'Em andamento', finalizado: 'Finalizado' };
const form = reactive({ responsible: '', squad: '', url: '', notes: '' });
const filtered = computed(() => deployments.value.filter(item =>
    (filter.value === 'todos' || item.status === filter.value) &&
    `${item.responsible} ${item.squad} ${item.url} ${item.id}`.toLocaleLowerCase('pt-BR').includes(search.value.toLocaleLowerCase('pt-BR'))
));
const counts = computed(() => Object.fromEntries(statuses.map(status => [status, deployments.value.filter(item => item.status === status).length])));
const positions = computed(() => Object.fromEntries(deployments.value.map((item, index) => [item.id, index + 1])));
const queueBusy = computed(() => loading.value || clearing.value || saving.value || updating.size > 0 || editingNotes.value !== null);
let timer;
let fetching = false;
let disposed = false;
let mutationVersion = 0;

async function request(path = '', options = {}) {
    const response = await fetch(`/api/deployments${path}`, {
        credentials: 'same-origin', ...options,
        headers: { Accept: 'application/json', 'Content-Type': 'application/json',
            'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        const failure = new Error(response.status === 419 ? 'Sua sessão expirou. Recarregue a página e tente novamente.' :
            response.status === 422 ? 'Confira os campos informados.' : 'Não foi possível salvar. Tente novamente.');
        failure.fields = body.errors || {};
        throw failure;
    }
    return body;
}
async function refresh() {
    if (fetching || saving.value || clearing.value || updating.size || editingNotes.value !== null) return;
    fetching = true;
    const version = mutationVersion;
    try {
        const records = await request();
        if (!disposed && version === mutationVersion) { deployments.value = records; error.value = ''; }
    } catch { if (!disposed) error.value = 'Não foi possível atualizar a fila. Verifique sua conexão.'; }
    finally { loading.value = false; fetching = false; }
}
async function createDeployment() {
    if (saving.value || clearing.value) return;
    saving.value = true; mutationVersion++; error.value = ''; notice.value = ''; fieldErrors.value = {};
    try {
        const record = await request('', { method: 'POST', body: JSON.stringify(form) });
        deployments.value.push(record);
        Object.assign(form, { responsible: '', squad: '', url: '', notes: '' });
        notice.value = `Deploy #${record.id} adicionado à fila.`;
    } catch (failure) { error.value = failure.message; fieldErrors.value = failure.fields || {}; }
    finally { saving.value = false; }
}
async function changeStatus(item, event) {
    const select = event.target;
    const status = select.value;
    select.value = item.status;
    if (clearing.value || updating.has(item.id) || status === item.status) return;
    updating.add(item.id); mutationVersion++; error.value = ''; notice.value = '';
    try {
        const record = await request(`/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
        Object.assign(item, record); select.value = record.status;
        notice.value = `Deploy #${item.id}: ${labels[record.status]}.`;
    } catch (failure) { error.value = failure.message; }
    finally { updating.delete(item.id); }
}
async function clearFinished() {
    if (loading.value || clearing.value || saving.value || updating.size || editingNotes.value !== null || !counts.value.finalizado) return;
    if (!window.confirm('Excluir permanentemente TODOS os registros finalizados, inclusive os ocultos pela busca ou filtro? Os demais status serão mantidos.')) return;
    clearing.value = true; mutationVersion++; error.value = ''; notice.value = '';
    try {
        const result = await request('/finished', { method: 'DELETE' });
        const records = await request();
        deployments.value = records;
        notice.value = `${result.deleted} registro(s) finalizado(s) removido(s).`;
    } catch (failure) {
        error.value = 'Não foi possível concluir a limpeza e atualizar a fila. Atualize a página para conferir os registros. ' + failure.message;
    } finally { clearing.value = false; }
}
async function moveDeployment(item, direction) {
    if (queueBusy.value) return;
    clearing.value = true; mutationVersion++; error.value = ''; notice.value = '';
    try {
        deployments.value = await request(`/${item.id}/move`, { method: 'PATCH', body: JSON.stringify({ direction }) });
        notice.value = `Deploy #${item.id} movido para a posição ${positions.value[item.id]}.`;
    } catch (failure) { error.value = failure.message; }
    finally { clearing.value = false; }
}
async function deleteDeployment(item) {
    if (queueBusy.value) return;
    if (!window.confirm(`Excluir permanentemente o deploy #${item.id}, de ${item.responsible} (${item.squad})?`)) return;
    clearing.value = true; mutationVersion++; error.value = ''; notice.value = '';
    try {
        await request(`/${item.id}`, { method: 'DELETE' });
        deployments.value = deployments.value.filter(record => record.id !== item.id);
        notice.value = `Deploy #${item.id} excluído da fila.`;
    } catch (failure) { error.value = failure.message; }
    finally { clearing.value = false; }
}
function editNotes(item) {
    if (clearing.value || updating.size) return;
    editingNotes.value = item.id;
    notesDraft.value = item.notes || '';
    notesError.value = '';
    mutationVersion++;
}
async function saveNotes(item) {
    if (clearing.value || updating.has(item.id)) return;
    updating.add(item.id); mutationVersion++; notesError.value = ''; notice.value = '';
    try {
        const record = await request(`/${item.id}`, { method: 'PATCH', body: JSON.stringify({ notes: notesDraft.value }) });
        Object.assign(item, record);
        editingNotes.value = null;
        notice.value = `Observação do deploy #${item.id} salva.`;
    } catch (failure) {
        notesError.value = failure.fields?.notes ? 'A observação deve ter até 2.000 caracteres.' : failure.message;
    } finally { updating.delete(item.id); }
}
function date(value) { return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)); }
function host(value) { try { return new URL(value).host; } catch { return value; } }
onMounted(() => { refresh(); timer = setInterval(refresh, 10000); });
onUnmounted(() => { disposed = true; clearInterval(timer); });
</script>

<template>
    <div class="shell">
        <header class="topbar"><a class="brand" href="/"><span class="brand-icon">↗</span> deploy<span class="brand-light">queue</span></a><span class="team-label">WORKSPACE DO TIME</span></header>
        <main>
            <div class="heading"><div><p class="eyebrow">ORGANIZE. ACOMPANHE. PUBLIQUE.</p><h1>Cada deploy, no seu lugar<span>.</span></h1><p class="subtitle">Uma fila compartilhada para manter o time em sincronia.</p></div><button class="secondary" @click="refresh" :disabled="loading">↻ Atualizar fila</button></div>
            <section class="stats" aria-label="Resumo da fila">
                <button v-for="(status, index) in statuses" :key="status" class="stat" :class="{ selected: filter === status }" @click="filter = filter === status ? 'todos' : status">
                    <span class="stat-top"><span class="dot" :class="`status-${index}`"></span>{{ labels[status] }}<span class="stat-arrow">↗</span></span><strong>{{ counts[status] }}</strong><span class="stat-bottom">{{ index === 0 ? 'Prontos para entrar em ação' : index === 1 ? 'Acontecendo agora' : 'Deploys concluídos' }}</span>
                </button>
            </section>
            <div role="alert" v-if="error" class="message error">{{ error }}</div>
            <div role="status" aria-live="polite" v-if="notice" class="message success">{{ notice }}</div>
            <div class="workspace">
                <section class="queue panel">
                    <div class="panel-heading"><div><h2>Fila de deploys <span class="count">{{ deployments.length }}</span></h2><p>Ordem ajustável. Os movimentos consideram a fila completa.</p></div><span class="live"><span></span> Atualiza a cada 10s</span></div>
                    <div class="toolbar"><label class="search"><span aria-hidden="true">⌕</span><input v-model="search" aria-label="Buscar por responsável, squad ou link" placeholder="Buscar responsável, squad ou link..."></label><select v-model="filter" aria-label="Filtrar por status"><option value="todos">Todos os status</option><option v-for="status in statuses" :key="status" :value="status">{{ labels[status] }}</option></select></div>
                    <div v-if="loading" class="empty" role="status">Carregando a fila...</div>
                    <div v-else-if="!filtered.length" class="empty"><div class="empty-icon">↗</div><h3>{{ deployments.length ? 'Nenhum deploy encontrado' : 'Tudo pronto para o primeiro deploy' }}</h3><p>{{ deployments.length ? 'Ajuste a busca ou o filtro para ver outros registros.' : 'Preencha os dados ao lado para colocar seu deploy na fila.' }}</p></div>
                    <div v-else class="records">
                        <article v-for="item in filtered" :key="item.id" class="record">
                            <span class="record-number" :title="`ID do registro: #${item.id}`">{{ positions[item.id] }}º<span class="record-id">#{{ item.id }}</span></span>
                            <div class="record-details"><h3>{{ item.responsible }}</h3><p><span class="squad">{{ item.squad }}</span><span class="record-date">{{ date(item.created_at) }}</span></p><a :href="item.url" target="_blank" rel="noopener noreferrer" :title="item.url">{{ host(item.url) }} ↗</a>
                                <form v-if="editingNotes === item.id" class="notes-editor" @submit.prevent="saveNotes(item)">
                                    <label :for="`notes-${item.id}`">Observação <span>(opcional)</span></label>
                                    <textarea :id="`notes-${item.id}`" v-model="notesDraft" maxlength="2000" rows="3" :disabled="updating.has(item.id)" :aria-invalid="!!notesError"></textarea>
                                    <small v-if="notesError" class="field-error" role="alert">{{ notesError }}</small>
                                    <div class="notes-actions"><button type="submit" class="secondary" :disabled="updating.has(item.id)">{{ updating.has(item.id) ? 'Salvando...' : 'Salvar observação' }}</button><button type="button" class="secondary" :disabled="updating.has(item.id)" @click="editingNotes = null">Cancelar</button></div>
                                </form>
                                <div v-else class="notes-display"><p v-if="item.notes" class="notes-text">{{ item.notes }}</p><button type="button" class="notes-button" :disabled="clearing || updating.size > 0" @click="editNotes(item)">{{ item.notes ? 'Editar observação' : '+ Adicionar observação' }}</button></div>
                                <div class="record-actions" :aria-label="`Ações do deploy #${item.id}`">
                                    <button type="button" class="secondary" :disabled="queueBusy || positions[item.id] === 1" :aria-label="`Mover deploy #${item.id} para cima`" title="Subir uma posição na fila completa" @click="moveDeployment(item, 'up')">↑ Subir</button>
                                    <button type="button" class="secondary" :disabled="queueBusy || positions[item.id] === deployments.length" :aria-label="`Mover deploy #${item.id} para baixo`" title="Descer uma posição na fila completa" @click="moveDeployment(item, 'down')">↓ Descer</button>
                                    <button type="button" class="secondary" :disabled="queueBusy || positions[item.id] === deployments.length" :aria-label="`Mover deploy #${item.id} para o fim`" @click="moveDeployment(item, 'end')">Mover para o fim</button>
                                    <button type="button" class="secondary delete-record" :disabled="queueBusy" :aria-label="`Excluir deploy #${item.id}`" @click="deleteDeployment(item)">Excluir</button>
                                </div>
                            </div>
                            <label class="status-control"><span class="sr-only">Status do deploy #{{ item.id }}</span><select :value="item.status" :class="`badge-${statuses.indexOf(item.status)}`" :disabled="clearing || updating.has(item.id)" @change="changeStatus(item, $event)"><option v-for="status in statuses" :key="status" :value="status">{{ labels[status] }}</option></select><small v-if="updating.has(item.id)">Salvando...</small></label>
                        </article>
                    </div>
                    <div class="queue-footer">{{ filtered.length }} {{ filtered.length === 1 ? 'registro' : 'registros' }} <button class="secondary" type="button" :disabled="loading || clearing || saving || updating.size > 0 || editingNotes !== null || !counts.finalizado" @click="clearFinished">{{ clearing ? 'Limpando...' : 'Limpar finalizados' }}</button></div>
                </section>
                <aside class="panel create-panel"><div class="new-icon">+</div><h2>Novo deploy</h2><p>Vai publicar? Reserve seu lugar na fila.</p>
                    <form @submit.prevent="createDeployment">
                        <label for="responsible">Responsável</label><input id="responsible" v-model.trim="form.responsible" required maxlength="100" placeholder="Nome de quem fará o deploy" :aria-invalid="!!fieldErrors.responsible"><small v-if="fieldErrors.responsible" class="field-error">Informe um responsável com até 100 caracteres.</small>
                        <label for="squad">Squad</label><input id="squad" v-model.trim="form.squad" required maxlength="100" placeholder="Ex.: Objetivos" :aria-invalid="!!fieldErrors.squad"><small v-if="fieldErrors.squad" class="field-error">Informe o squad com até 100 caracteres.</small>
                        <label for="url">Link do deploy</label><input id="url" v-model.trim="form.url" type="url" required maxlength="2048" pattern="https?://.+" placeholder="https://github.com/..." :aria-invalid="!!fieldErrors.url"><small v-if="fieldErrors.url" class="field-error">Informe uma URL válida com http:// ou https://.</small>
                        <label for="notes">Observação <span class="optional">(opcional)</span></label><textarea id="notes" v-model="form.notes" maxlength="2000" rows="3" placeholder="Informações adicionais sobre o deploy..." :aria-invalid="!!fieldErrors.notes"></textarea><small v-if="fieldErrors.notes" class="field-error">A observação deve ter até 2.000 caracteres.</small>
                        <div class="initial-status"><span class="dot status-0"></span> Entra na fila como <strong>Aguardando</strong></div>
                        <button class="primary" type="submit" :disabled="saving || clearing">{{ saving ? 'Adicionando...' : '+ Adicionar à fila' }}</button>
                    </form>
                    <p class="help">Depois de cadastrar, altere o status diretamente na fila. Não é necessário fazer login.</p>
                </aside>
            </div>
            <footer><span>deployqueue <span class="footer-dot">·</span> Menos ruído, mais entregas.</span><span>Acesso compartilhado · Sem autenticação</span></footer>
        </main>
    </div>
</template>
