// Shared provider/model menus; no conversation state or Markdown.
async function loadAgentModels() {
  try {
    const providers = await apiGet('/agent/providers');
    const orProv = providers.find(p => p.id === 'openrouter');
    if (!orProv) return;
    for (const selectId of ['agent-model', 'report-model']) {
      const modelSel = document.getElementById(selectId);
      const previous = modelSel.value;
      modelSel.replaceChildren();
      if (orProv.models.length) {
        orProv.models.forEach((model, index) => {
          const option = document.createElement('option');
          option.value = model.id;
          option.textContent = '#' + (index + 1) + ' ' + model.display;
          modelSel.appendChild(option);
        });
        if (orProv.models.some(model => model.id === previous)) {
          modelSel.value = previous;
        }
      } else {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '今日沒有可用的熱門免費工具模型';
        modelSel.appendChild(option);
      }
      modelSel.disabled = !orProv.models.length;
    }
  } catch (e) {
    console.error('載入模型清單失敗:', e);
  }
}

async function refreshAgentModels() {
  const btn = document.getElementById('agent-refresh-btn');
  btn.disabled = true;
  btn.textContent = '⏳';
  try {
    await apiPost('/agent/models/refresh', {});
    await loadAgentModels();
  } catch (e) {
    alert('刷新模型列表失敗：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 刷新模型列表';
  }
}
