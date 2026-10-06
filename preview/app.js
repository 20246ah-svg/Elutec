(() => {
  'use strict';

  const $ = selector => document.querySelector(selector);
  const $$ = selector => Array.from(document.querySelectorAll(selector));
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const roiInputs = {
    x: $('#roi-x'), y: $('#roi-y'), w: $('#roi-w'), h: $('#roi-h')
  };
  const roi = { x: 300, y: 150, w: 200, h: 200, shape: 'circle' };
  const channels = { r: 143.4, g: 128.1, b: 96.3 };
  let running = false;
  let tick = 0;
  let toastTimer = null;
  let scanTimer = null;
  let sessionStartedAt = 0;
  let sessionElapsed = 0;
  let dragOrigin = null;

  function showToast(message) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('show'), 2400);
  }

  function setConnection(message, active = false) {
    $('#connection-text').textContent = message;
    $('#connection-badge').classList.toggle('is-live', active);
  }

  function syncRoi() {
    Object.entries(roiInputs).forEach(([key, input]) => {
      const value = Number.parseInt(input.value, 10);
      const min = key === 'w' || key === 'h' ? 20 : 0;
      const max = key === 'x' || key === 'w' ? 1920 : 1080;
      roi[key] = clamp(Number.isFinite(value) ? value : min, min, max);
      input.value = String(roi[key]);
    });
    roi.x = Math.min(roi.x, 1920 - roi.w);
    roi.y = Math.min(roi.y, 1080 - roi.h);
    roiInputs.x.value = String(roi.x);
    roiInputs.y.value = String(roi.y);
    const summary = `X ${roi.x}   Y ${roi.y}   W ${roi.w}   H ${roi.h}`;
    $('#roi-summary').textContent = summary;
    $('#roi-head-summary').textContent = `${roi.w} × ${roi.h} px`;
    $('#roi-area').innerHTML = `${(roi.w * roi.h).toLocaleString('ru-RU')} <small>px²</small>`;
    $('#scene-roi-text').textContent = `${roi.shape === 'circle' ? 'КРУГ' : 'ПРЯМОУГОЛЬНИК'} · ${roi.w} × ${roi.h} PX`;
    const overlay = $('#roi-overlay');
    overlay.style.left = `${(roi.x / 1920) * 100}%`;
    overlay.style.top = `${(roi.y / 1080) * 100}%`;
    overlay.style.width = `${(roi.w / 1920) * 100}%`;
    overlay.style.height = `${(roi.h / 1080) * 100}%`;
  }

  function setShape(shape) {
    roi.shape = shape;
    $('#roi-circle').classList.toggle('active', shape === 'circle');
    $('#roi-rectangle').classList.toggle('active', shape === 'rect');
    $('#roi-overlay').classList.toggle('roi-circle', shape === 'circle');
    $('#roi-overlay').classList.toggle('roi-rect', shape === 'rect');
    syncRoi();
  }

  function offsetRoi(key, delta) {
    const input = roiInputs[key];
    input.value = String((Number.parseInt(input.value, 10) || 0) + delta);
    syncRoi();
  }

  function changeSize(factor) {
    const centerX = roi.x + roi.w / 2;
    const centerY = roi.y + roi.h / 2;
    roi.w = clamp(Math.round(roi.w * factor), 20, 1920);
    roi.h = clamp(Math.round(roi.h * factor), 20, 1080);
    roi.x = clamp(Math.round(centerX - roi.w / 2), 0, 1920 - roi.w);
    roi.y = clamp(Math.round(centerY - roi.h / 2), 0, 1080 - roi.h);
    Object.entries(roiInputs).forEach(([key, input]) => { input.value = String(roi[key]); });
    syncRoi();
  }

  function updateMetrics() {
    $('#metric-r').textContent = channels.r.toFixed(1);
    $('#metric-g').textContent = channels.g.toFixed(1);
    $('#metric-b').textContent = channels.b.toFixed(1);
    const ratio = Math.log10(Math.max(channels.b, 0.01) / Math.max(channels.r, 0.01));
    $('#metric-log').textContent = `${ratio < 0 ? '−' : '+'}${Math.abs(ratio).toFixed(4)}`;
    const rgb = channels;
    $('#color-swatch').style.background = `rgb(${Math.round(rgb.r / 300 * 255)}, ${Math.round(rgb.g / 300 * 255)}, ${Math.round(rgb.b / 300 * 255)})`;
    const score = running ? 1.24 + Math.max(0, Math.sin(tick / 33)) * 1.8 : 1.24;
    $('#transition-score').textContent = score.toFixed(2);
    $('#score-meter-fill').style.width = `${clamp(score * 10, 0, 100)}%`;
    $('#score-caption').textContent = score > 2.5 ? 'Возможное изменение состава сигнала' : 'Ожидание устойчивого сигнала';
  }

  function makeSeries(base, phase, amplitude) {
    const count = 44;
    const points = [];
    for (let i = 0; i < count; i += 1) {
      const drift = running ? Math.sin((i + tick / 2) * 0.11) * 4 : 0;
      const wave = Math.sin(i * 0.53 + phase) * amplitude + Math.cos(i * 0.19 + phase) * amplitude * 0.38;
      const value = clamp(base + wave + drift, 5, 295);
      const x = (i / (count - 1)) * 760;
      const y = 140 - (value / 300) * 132;
      points.push([x, y]);
    }
    return points;
  }

  function pointsString(points) {
    return points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  }

  function drawChart() {
    const data = {
      r: makeSeries(channels.r, 0.2, 9),
      g: makeSeries(channels.g, 1.8, 7),
      b: makeSeries(channels.b, 3.1, 6)
    };
    Object.entries(data).forEach(([key, points]) => {
      $(`#line-${key}`).setAttribute('points', pointsString(points));
      $(`#area-${key}`).setAttribute('points', `${pointsString(points)} 760,140 0,140`);
      const marker = points[points.length - 1];
      $(`#cursor-${key}`).setAttribute('cx', marker[0].toFixed(1));
      $(`#cursor-${key}`).setAttribute('cy', marker[1].toFixed(1));
    });
    const x = data.r[data.r.length - 1][0];
    $('#chart-cursor').setAttribute('x1', x);
    $('#chart-cursor').setAttribute('x2', x);
    updateMetrics();
  }

  function formatTime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return [hours, minutes, secs].map(value => String(value).padStart(2, '0')).join(':');
  }

  function updateSimulation() {
    tick += 1;
    if (running) {
      channels.r = clamp(channels.r + Math.sin(tick / 8) * 0.8 + (Math.random() - 0.5) * 2.2, 58, 250);
      channels.g = clamp(channels.g + Math.cos(tick / 9) * 0.55 + (Math.random() - 0.5) * 1.8, 45, 220);
      channels.b = clamp(channels.b + Math.sin(tick / 11 + 1.4) * 0.5 + (Math.random() - 0.5) * 1.5, 30, 190);
      sessionElapsed = Math.floor((Date.now() - sessionStartedAt) / 1000);
      $('#session-timer').textContent = formatTime(sessionElapsed);
      $('#video-time').textContent = formatTime(sessionElapsed);
    }
    $('#session-state').textContent = running ? 'Демо-анализ' : 'Ожидание';
    $('#chart-state').classList.toggle('is-live', running);
    $('#chart-state').innerHTML = `<i></i> ${running ? 'симуляция сигнала' : 'демо-данные'}`;
    drawChart();
  }

  function chooseDevice(row) {
    $$('.device-row').forEach(item => {
      item.classList.toggle('selected', item === row);
      item.querySelector('.device-check').textContent = item === row ? '●' : '○';
    });
    const source = row.dataset.source || '0';
    const name = row.querySelector('strong').textContent;
    $('#source-input').value = source;
    $('#selected-device').textContent = `${name} · ${source}`;
    showToast(`Выбран источник: ${name}`);
  }

  function scanDevice(kind) {
    setConnection(`ПОИСК · ${kind.toUpperCase()}`);
    showToast(`Поиск «${kind}» показан только в макете`);
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(() => setConnection('НЕТ СИГНАЛА'), 1400);
  }

  function toggleRunning() {
    running = !running;
    if (running) {
      sessionStartedAt = Date.now() - sessionElapsed * 1000;
      $('#start-label').textContent = 'Остановить анализ';
      $('#start-analysis').classList.add('is-running');
      $('#session-state').textContent = 'Демо-анализ';
      setConnection('ДЕМО-СИМУЛЯЦИЯ', true);
      showToast('Запущена только визуальная симуляция интерфейса');
    } else {
      sessionElapsed = Math.floor((Date.now() - sessionStartedAt) / 1000);
      $('#start-label').textContent = 'Начать анализ';
      $('#start-analysis').classList.remove('is-running');
      $('#session-state').textContent = 'Ожидание';
      setConnection('НЕТ СИГНАЛА');
      showToast('Демонстрация остановлена');
    }
  }

  $('#theme-toggle').addEventListener('click', () => {
    const isLight = document.body.classList.toggle('theme-light');
    const icon = $('#theme-toggle use');
    icon.setAttribute('href', isLight ? '#i-moon' : '#i-sun');
    $('#theme-toggle').title = isLight ? 'Тёмная тема' : 'Светлая тема';
    $('#theme-toggle').setAttribute('aria-label', isLight ? 'Переключить на тёмную тему' : 'Переключить на светлую тему');
  });

  $$('.device-row').forEach(row => row.addEventListener('click', () => chooseDevice(row)));
  $$('[data-scan]').forEach(button => button.addEventListener('click', () => scanDevice(button.dataset.scan)));
  $('#scan-refresh').addEventListener('click', () => scanDevice('устройств'));
  $('#stage-scan').addEventListener('click', () => scanDevice('USB-камера'));
  $('#stage-connect').addEventListener('click', () => scanDevice('USB-камера'));

  $('#apply-source').addEventListener('click', () => {
    const source = $('#source-input').value.trim() || '0';
    $('#selected-device').textContent = `Источник · ${source}`;
    setConnection('ИСТОЧНИК ВЫБРАН');
    showToast(`Источник ${source} сохранён в макете`);
  });
  $('#reconnect').addEventListener('click', () => {
    setConnection('ПРОВЕРКА ИСТОЧНИКА');
    showToast('Реальное подключение доступно в настольном приложении');
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(() => setConnection('НЕТ СИГНАЛА'), 1200);
  });
  $('#open-file').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', event => {
    const file = event.target.files && event.target.files[0];
    if (file) showToast(`Выбран файл «${file.name}» · обработка не запускается в макете`);
  });
  $('#browse-folder').addEventListener('click', () => showToast('В настольном приложении здесь открывается выбор папки'));

  $$('.shape-button').forEach(button => button.addEventListener('click', () => setShape(button.dataset.shape)));
  Object.values(roiInputs).forEach(input => input.addEventListener('change', syncRoi));
  $$('[data-step]').forEach(button => button.addEventListener('click', () => offsetRoi(button.dataset.step, Number(button.dataset.delta))));
  $('#roi-shrink').addEventListener('click', () => changeSize(0.8));
  $('#roi-grow').addEventListener('click', () => changeSize(1.2));
  $('#roi-reset').addEventListener('click', () => {
    Object.assign(roi, { x: 300, y: 150, w: 200, h: 200 });
    Object.entries(roiInputs).forEach(([key, input]) => { input.value = String(roi[key]); });
    syncRoi();
    showToast('Область ROI возвращена к исходному размеру');
  });

  const stage = $('#video-stage');
  const overlay = $('#roi-overlay');
  overlay.addEventListener('pointerdown', event => {
    event.preventDefault();
    dragOrigin = { x: event.clientX, y: event.clientY, roiX: roi.x, roiY: roi.y };
    overlay.setPointerCapture(event.pointerId);
  });
  overlay.addEventListener('pointermove', event => {
    if (!dragOrigin) return;
    const rect = stage.getBoundingClientRect();
    roi.x = clamp(Math.round(dragOrigin.roiX + (event.clientX - dragOrigin.x) / rect.width * 1920), 0, 1920 - roi.w);
    roi.y = clamp(Math.round(dragOrigin.roiY + (event.clientY - dragOrigin.y) / rect.height * 1080), 0, 1080 - roi.h);
    roiInputs.x.value = String(roi.x);
    roiInputs.y.value = String(roi.y);
    syncRoi();
  });
  const endDrag = () => { dragOrigin = null; };
  overlay.addEventListener('pointerup', endDrag);
  overlay.addEventListener('pointercancel', endDrag);

  $('#start-analysis').addEventListener('click', toggleRunning);
  $('#refresh-chart').addEventListener('click', () => { tick += 5; drawChart(); showToast('График обновлён'); });

  const settingsTabs = {
    video: { title: 'Видео и запись', description: 'Источники, воспроизведение файлов и сохранение видеопотока.', rows: [['Скорость воспроизведения', '1.0×', 'Скорость чтения видеофайла'], ['Запись сессии', 'Включена', 'Сохранение исходного потока'], ['Автоостановка', 'Включена', 'Остановить анализ в конце файла']] },
    graphs: { title: 'Каналы и графики', description: 'Отображение исходных значений RGB и вычисляемых показателей.', rows: [['Каналы R / G / B', 'Включены', 'Средние значения выбранной ROI'], ['Log10 (B/R)', 'Включён', 'Логарифмическое отношение синего и красного'], ['Профиль', 'Сбалансированный', 'Частота обновления графиков']] },
    roi: { title: 'Область анализа', description: 'Настройка геометрии и поведения выделенной зоны.', rows: [['Форма', roi.shape === 'circle' ? 'Круг' : 'Прямоугольник', 'Круглая или прямоугольная ROI'], ['Перетаскивание', 'Включено', 'Перемещение области непосредственно на кадре'], ['Размер', `${roi.w} × ${roi.h} px`, 'Текущая область измерения']] },
    alerts: { title: 'Автометки и уведомления', description: 'Контроль переходов SAT → AROM → BR → ABR.', rows: [['Автометки', 'Включены', 'Маркировка характерных переходов'], ['Подтверждение', '5 сек', 'Фильтр кратковременных шумовых пиков'], ['Повторное срабатывание', '30 сек', 'Интервал между событиями']] },
    performance: { title: 'Производительность', description: 'Баланс между отзывчивостью интерфейса и детализацией сигнала.', rows: [['Профиль', 'Сбалансированный', 'Подходит для лабораторного ПК'], ['Интервал анализа', '15 мс', 'Частота обработки кадров'], ['История графика', '50 000 точек', 'Максимальная длина буфера']] }
  };

  function renderSettingsTab(key) {
    const tab = settingsTabs[key];
    if (!tab) return;
    $('#settings-content').innerHTML = `<h3>${tab.title}</h3><p>${tab.description}</p>${tab.rows.map(([label, value, note]) => `<div class="settings-row"><div><strong>${label}</strong><small>${note}</small></div><span class="settings-value">${value}</span></div>`).join('')}`;
    $$('.settings-tab').forEach(button => button.classList.toggle('active', button.dataset.tab === key));
  }

  const settingsModal = $('#settings-modal');
  const licenseModal = $('#license-modal');
  function openDialog(dialog) { if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', ''); }
  $('#settings-open').addEventListener('click', () => { renderSettingsTab('video'); openDialog(settingsModal); });
  $('#rail-settings').addEventListener('click', () => { renderSettingsTab('video'); openDialog(settingsModal); });
  $('#license-open').addEventListener('click', () => openDialog(licenseModal));
  $('#rail-license').addEventListener('click', () => openDialog(licenseModal));
  $$('.settings-tab').forEach(button => button.addEventListener('click', () => renderSettingsTab(button.dataset.tab)));
  [settingsModal, licenseModal].forEach(dialog => dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }));
  $('#copy-license-id').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText('ELUTEC-DEMO-ID'); } catch (_) { /* clipboard may be blocked on file:// */ }
    showToast('Демо-идентификатор скопирован');
  });

  syncRoi();
  drawChart();
  window.setInterval(updateSimulation, 1100);
})();
