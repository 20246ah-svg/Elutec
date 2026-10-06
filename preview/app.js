(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const toast = $('#toast');
  let toastTimer = null;
  let running = false;
  let tick = 0;
  let lastMessageTimer = null;

  const roi = { x: 300, y: 150, w: 200, h: 200, shape: 'circle' };
  const inputs = { x: $('#roi-x'), y: $('#roi-y'), w: $('#roi-w'), h: $('#roi-h') };
  const channels = { r: 124.8, g: 98.3, b: 72.5 };

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
  }

  function setConnection(message, isLive = false) {
    $('#connection-text').textContent = message;
    $('#connection-badge').classList.toggle('is-live', isLive);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function syncRoi() {
    Object.keys(inputs).forEach(key => {
      const parsed = Number.parseInt(inputs[key].value, 10);
      roi[key] = Number.isFinite(parsed) ? parsed : 0;
      inputs[key].value = String(roi[key]);
    });
    roi.x = clamp(roi.x, 0, 1920);
    roi.y = clamp(roi.y, 0, 1080);
    roi.w = clamp(roi.w, 20, 1920);
    roi.h = clamp(roi.h, 20, 1080);
    Object.keys(inputs).forEach(key => { inputs[key].value = String(roi[key]); });
    $('#roi-summary').innerHTML = `<span class="roi-summary-mark">⌖</span> X: ${roi.x}&nbsp;&nbsp; Y: ${roi.y}&nbsp;&nbsp; W: ${roi.w}&nbsp;&nbsp; H: ${roi.h}`;
    $('#scene-roi-text').textContent = `${roi.shape === 'circle' ? 'Круг' : 'Прямоугольник'} · X:${roi.x} Y:${roi.y} · ${roi.w} × ${roi.h} px`;
  }

  function offsetRoi(key, delta) {
    const current = Number.parseInt(inputs[key].value, 10) || 0;
    inputs[key].value = String(current + delta);
    syncRoi();
  }

  function setShape(shape) {
    roi.shape = shape;
    $$('.segment').forEach(button => button.classList.toggle('active', button.dataset.shape === shape));
    const overlay = $('#roi-overlay');
    overlay.classList.toggle('roi-circle', shape === 'circle');
    overlay.classList.toggle('roi-rect', shape === 'rect');
    syncRoi();
  }

  function changeSize(factor) {
    const centerX = roi.x + roi.w / 2;
    const centerY = roi.y + roi.h / 2;
    roi.w = clamp(Math.round(roi.w * factor), 20, 1920);
    roi.h = clamp(Math.round(roi.h * factor), 20, 1080);
    roi.x = clamp(Math.round(centerX - roi.w / 2), 0, 1920);
    roi.y = clamp(Math.round(centerY - roi.h / 2), 0, 1080);
    Object.keys(inputs).forEach(key => { inputs[key].value = String(roi[key]); });
    syncRoi();
  }

  function updateMetrics() {
    if (running) {
      const phase = tick / 7;
      channels.r = clamp(channels.r + Math.sin(phase) * 0.32 + (Math.random() - 0.5) * 0.65, 70, 220);
      channels.g = clamp(channels.g + Math.cos(phase * 0.75) * 0.2 + (Math.random() - 0.5) * 0.52, 50, 180);
      channels.b = clamp(channels.b + Math.sin(phase * 0.55 + 1.2) * 0.2 + (Math.random() - 0.5) * 0.42, 30, 160);
    }
    $('#metric-r').textContent = channels.r.toFixed(1);
    $('#metric-g').textContent = channels.g.toFixed(1);
    $('#metric-b').textContent = channels.b.toFixed(1);
    const logRatio = Math.log10(Math.max(channels.b, 0.01) / Math.max(channels.r, 0.01));
    $('#metric-log').textContent = `${logRatio < 0 ? '−' : '+'}${Math.abs(logRatio).toFixed(4)}`;
    $('#transition-score').innerHTML = `${(1.24 + (running ? Math.max(0, Math.sin(tick / 38)) * 0.42 : 0)).toFixed(2)} <small>/ 10</small>`;
  }

  function chartPoints(base, phase, amplitude, count = 20) {
    const minY = 17;
    const maxY = 169;
    const range = maxY - minY;
    const points = [];
    for (let i = 0; i < count; i += 1) {
      const x = 38 + (292 * i / (count - 1));
      const wave = Math.sin((i + phase) * 0.77) * amplitude + Math.cos((i + phase) * 0.31) * amplitude * 0.42;
      const drift = running ? Math.sin((i + tick / 3) * 0.2) * 2 : 0;
      const value = clamp(base + wave + drift, 8, 292);
      const y = maxY - (value / 300) * range;
      points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return points.join(' ');
  }

  function updateChart() {
    tick += 1;
    $('#line-r').setAttribute('points', chartPoints(channels.r, tick * 0.25, 8));
    $('#line-g').setAttribute('points', chartPoints(channels.g, tick * 0.25 + 3, 7));
    $('#line-b').setAttribute('points', chartPoints(channels.b, tick * 0.25 + 6, 6));
    const x = 38 + ((tick * 3) % 292);
    $('#chart-cursor').setAttribute('x1', x);
    $('#chart-cursor').setAttribute('x2', x);
    const cursorY = channel => 169 - (channel / 300) * 152;
    $('#cursor-r').setAttribute('cx', x); $('#cursor-r').setAttribute('cy', cursorY(channels.r));
    $('#cursor-g').setAttribute('cx', x); $('#cursor-g').setAttribute('cy', cursorY(channels.g));
    $('#cursor-b').setAttribute('cx', x); $('#cursor-b').setAttribute('cy', cursorY(channels.b));
    updateMetrics();
    const seconds = tick % 60;
    const minutes = Math.floor(tick / 60);
    $('#video-time').textContent = `00:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    $('#chart-state').innerHTML = `<span class="tiny-dot"></span> ${running ? 'сигнал обновляется' : 'демо-данные'}`;
  }

  $('#theme-toggle').addEventListener('click', () => {
    document.body.classList.toggle('theme-dark');
    $('#theme-toggle').textContent = document.body.classList.contains('theme-dark') ? 'Светлая тема' : 'Тёмная тема';
  });

  $$('.segment').forEach(button => button.addEventListener('click', () => setShape(button.dataset.shape)));
  Object.values(inputs).forEach(input => input.addEventListener('change', syncRoi));
  $$('[data-step]').forEach(button => button.addEventListener('click', () => offsetRoi(button.dataset.step, Number(button.dataset.delta))));
  $('#roi-enlarge').addEventListener('click', () => changeSize(1.2));
  $('#roi-shrink').addEventListener('click', () => changeSize(0.8));
  $('#roi-reset').addEventListener('click', () => {
    Object.assign(roi, { x: 300, y: 150, w: 200, h: 200 });
    Object.keys(inputs).forEach(key => { inputs[key].value = String(roi[key]); });
    syncRoi();
  });

  $$('.device-row').forEach(row => row.addEventListener('click', () => {
    $$('.device-row').forEach(item => item.classList.remove('selected'));
    row.classList.add('selected');
    const source = row.dataset.source || '0';
    $('#source-input').value = source;
    $('#selected-device').textContent = `Выбранное устройство: ${row.querySelector('strong').textContent} (${source})`;
    showToast(`Выбран источник ${source}`);
  }));

  function scanDevice(kind) {
    setConnection(`Поиск · ${kind.toLowerCase()}`);
    showToast(`В демо-макете поиск ${kind.toLowerCase()} не запускается`);
    clearTimeout(lastMessageTimer);
    lastMessageTimer = setTimeout(() => setConnection('Демо-режим · нет источника'), 1300);
  }
  $$('[data-scan]').forEach(button => button.addEventListener('click', () => scanDevice(button.dataset.scan)));
  $('#scan-refresh').addEventListener('click', () => scanDevice('устройств'));

  $('#apply-source').addEventListener('click', () => {
    const source = $('#source-input').value.trim() || '0';
    setConnection('Демо-режим · источник не подключён');
    $('#selected-device').textContent = `Источник для запуска: ${source}`;
    showToast('Источник сохранён только в макете интерфейса');
  });
  $('#reconnect').addEventListener('click', () => {
    setConnection('Проверка источника · демо');
    showToast('Подключение к камере доступно в установленном приложении');
    clearTimeout(lastMessageTimer);
    lastMessageTimer = setTimeout(() => setConnection('Демо-режим · нет источника'), 1400);
  });
  $('#open-file').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', event => {
    const file = event.target.files && event.target.files[0];
    if (file) showToast(`Выбран файл «${file.name}» — макет не запускает обработку`);
  });

  $('#start-analysis').addEventListener('click', () => {
    running = !running;
    $('#start-label').textContent = running ? 'Остановить демо-анализ' : 'Запустить анализ';
    $('#start-analysis').classList.toggle('is-running', running);
    if (running) {
      setConnection('Симуляция анализа', true);
      $('#chart-state').innerHTML = '<span class="tiny-dot"></span> симуляция активна';
      showToast('Запущена демонстрация интерфейса');
    } else {
      setConnection('Демо-режим · нет источника');
      $('#chart-state').innerHTML = '<span class="tiny-dot"></span> демо-данные';
      showToast('Демонстрация остановлена');
    }
  });
  $('#refresh-chart').addEventListener('click', () => {
    tick += 4;
    updateChart();
    showToast('График обновлён');
  });

  const settingsModal = $('#settings-modal');
  const settingsContent = $('#modal-content');
  const settingsTabs = {
    video: {
      title: 'Видео и запись', description: 'Управление локальными файлами, записью и окном воспроизведения.',
      rows: [['Скорость воспроизведения', '1.0×', 'По умолчанию для видеофайлов'], ['Запись сессии', 'Включена', 'Сохранять видеопоток в MKV'], ['Автоостановка', 'Включена', 'Завершать анализ в конце файла']]
    },
    graphs: {
      title: 'Графики и формулы', description: 'Выберите отображаемые каналы и настройте вычисляемые показатели.',
      rows: [['Каналы R, G, B', 'Включены', 'Отображать исходные значения RGB'], ['Индекс перехода', 'Включён', 'Показывать сводный Transition score'], ['Сглаживание', 'Сбалансировано', 'Профиль отрисовки истории']]
    },
    roi: {
      title: 'Область анализа ROI', description: 'Настройки интерактивной рамки и сохранения параметров ROI.',
      rows: [['Перемещение на видео', 'Включено', 'Корректировать область прямо на кадре'], ['Форма', roi.shape === 'circle' ? 'Круг' : 'Прямоугольник', 'Применяется к текущему источнику'], ['Размер', `${roi.w} × ${roi.h} px`, 'Изменяется кнопками в левой панели']]
    },
    alerts: {
      title: 'Автометки и уведомления', description: 'Настройка переходов между фракциями SAT → AROM → BR → ABR.',
      rows: [['Автоматические уведомления', 'Включены', 'Уведомлять оператора о переходах'], ['Подтверждение события', '5 сек', 'Защита от коротких шумовых пиков'], ['Повторное срабатывание', '30 сек', 'Интервал между одинаковыми метками']]
    },
    performance: {
      title: 'Производительность', description: 'Профиль нагрузки и частота обновления интерфейса.',
      rows: [['Профиль', 'Сбалансированный', 'Подходит для большинства лабораторных ПК'], ['Интервал обработки', '15 мс', 'Частота анализа кадров'], ['История графиков', '50 000 точек', 'Максимум данных в окне сессии']]
    }
  };

  function renderSettingsTab(key) {
    const tab = settingsTabs[key];
    if (!tab) return;
    settingsContent.innerHTML = `<h3>${tab.title}</h3><p>${tab.description}</p>${tab.rows.map(([label, value, hint]) => `<div class="setting-row"><div>${label}<small>${hint}</small></div><span class="fake-select">${value}</span></div>`).join('')}`;
    $$('.modal-tab').forEach(item => item.classList.toggle('active', item.dataset.tab === key));
  }
  $('#settings-open').addEventListener('click', () => {
    renderSettingsTab('video');
    settingsModal.showModal();
  });
  $$('.modal-tab').forEach(tab => tab.addEventListener('click', () => renderSettingsTab(tab.dataset.tab)));
  $('#license-open').addEventListener('click', () => $('#license-modal').showModal());
  $$('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  $$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  }));
  $('#paste-key').addEventListener('click', async () => {
    try {
      const value = await navigator.clipboard.readText();
      if (value) $('#license-key').value = value;
    } catch (_) {
      showToast('Вставьте ключ в установленном приложении');
    }
  });

  syncRoi();
  updateMetrics();
  updateChart();
  setInterval(updateChart, 900);
})();
