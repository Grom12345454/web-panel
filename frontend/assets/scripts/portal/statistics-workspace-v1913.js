/* Professional statistics workspace: shared filters, fast tables and safe CSV export. */
(() => {
  'use strict';

  const normalize = (value) => String(value || '').toLocaleLowerCase('ru-RU').replace(/\s+/g, ' ').trim();
  const safeText = (row) => normalize(row.innerText || row.textContent || '');
  const getRows = (tbody) => Array.from(tbody.querySelectorAll('tr')).filter((row) => {
    return !row.id && !row.classList.contains('stats-table-empty-row') && !row.querySelector('.empty');
  });

  const datePeriod = document.getElementById('stats-period-select');
  const dateFrom = document.getElementById('stats-date-from');
  const dateTo = document.getElementById('stats-date-to');
  const updateDateControls = () => {
    if (!datePeriod || !dateFrom || !dateTo) return;
    const custom = datePeriod.value === 'custom';
    dateFrom.disabled = !custom;
    dateTo.disabled = !custom;
    dateFrom.setAttribute('aria-disabled', String(!custom));
    dateTo.setAttribute('aria-disabled', String(!custom));
  };
  if (datePeriod) {
    document.querySelectorAll('[data-stats-period]').forEach((button) => {
      button.addEventListener('click', () => {
        datePeriod.value = button.dataset.statsPeriod || 'all';
        if (dateFrom) dateFrom.value = '';
        if (dateTo) dateTo.value = '';
        updateDateControls();
        const filterForm = datePeriod.closest('form');
        if (!filterForm) return;
        if (typeof filterForm.requestSubmit === 'function') filterForm.requestSubmit();
        else filterForm.submit();
      });
    });
    datePeriod.addEventListener('change', updateDateControls);
    [dateFrom, dateTo].filter(Boolean).forEach((input) => input.addEventListener('change', () => {
      datePeriod.value = 'custom';
      updateDateControls();
    }));
    const form = datePeriod.closest('form');
    if (form) form.addEventListener('submit', (event) => {
      if (datePeriod.value !== 'custom') return;
      if ((!dateFrom || !dateFrom.value) && (!dateTo || !dateTo.value)) {
        event.preventDefault();
        datePeriod.focus();
        window.alert('Для собственного периода укажите хотя бы одну границу даты.');
        return;
      }
      if (dateFrom && dateTo && dateFrom.value && dateTo.value && dateFrom.value > dateTo.value) {
        event.preventDefault();
        window.alert('Дата «С» не может быть позже даты «По».');
      }
    });
    updateDateControls();
  }

  document.querySelectorAll('table[data-statistics-table]').forEach((table) => {
    const tbody = table.tBodies && table.tBodies[0];
    if (!tbody) return;
    let allRows = getRows(tbody);
    // Keep table rows visually consistent with the Active Students register:
    // uncluttered cells, exact numeric values and compact semantic badges.
    const originalEmptyRows = Array.from(tbody.querySelectorAll('tr')).filter((row) => row.querySelector('.empty'));
    originalEmptyRows.forEach((row) => { row.dataset.statsEmpty = '1'; });

    const shell = document.createElement('div');
    shell.className = 'stats-table-toolbar';
    shell.setAttribute('role', 'group');
    shell.setAttribute('aria-label', 'Инструменты таблицы');

    let search = null;
    if (table.id !== 'direction-statistics-table') {
      const searchWrap = document.createElement('label');
      searchWrap.className = 'stats-table-search';
      const searchLabel = document.createElement('span');
      searchLabel.textContent = 'Быстрый поиск';
      search = document.createElement('input');
      search.type = 'search';
      search.placeholder = 'Имя, название, группа…';
      search.autocomplete = 'off';
      search.setAttribute('aria-label', 'Поиск по строкам таблицы');
      searchWrap.append(searchLabel, search);
      shell.append(searchWrap);
    }

    const pageSizeLabel = document.createElement('label');
    pageSizeLabel.className = 'stats-table-page-size';
    const pageSizeText = document.createElement('span');
    pageSizeText.textContent = 'Строк на странице';
    const pageSize = document.createElement('select');
    pageSize.setAttribute('aria-label', 'Количество строк на странице');
    [10, 25, 50, 100].forEach((size) => {
      const option = document.createElement('option');
      option.value = String(size);
      option.textContent = String(size);
      if (size === 25) option.selected = true;
      pageSize.append(option);
    });
    pageSizeLabel.append(pageSizeText, pageSize);
    shell.append(pageSizeLabel);

    const count = document.createElement('span');
    count.className = 'stats-table-result-count';
    count.setAttribute('aria-live', 'polite');
    shell.append(count);

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'btn btn-soft stats-table-export';
    exportButton.textContent = 'Экспорт CSV';
    exportButton.setAttribute('aria-label', 'Экспортировать отфильтрованные строки в CSV');
    shell.append(exportButton);

    const scroll = table.closest('.table-scroll') || table.parentElement;
    if (scroll && scroll.parentElement) scroll.parentElement.insertBefore(shell, scroll);

    const pager = document.createElement('div');
    pager.className = 'stats-table-pagination';
    const pagerInfo = document.createElement('span');
    pagerInfo.className = 'stats-table-pagination-info';
    pagerInfo.setAttribute('aria-live', 'polite');
    const prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'btn btn-soft';
    prev.textContent = '← Назад';
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn btn-soft';
    next.textContent = 'Вперёд →';
    pager.append(pagerInfo, prev, next);
    if (scroll && scroll.parentElement) scroll.parentElement.append(pager);

    const dynamicEmpty = document.createElement('tr');
    dynamicEmpty.className = 'stats-table-empty-row';
    const emptyCell = document.createElement('td');
    emptyCell.colSpan = Math.max(1, table.querySelectorAll('thead th').length);
    emptyCell.textContent = 'По выбранным условиям ничего не найдено. Измените поиск или фильтры.';
    dynamicEmpty.append(emptyCell);
    dynamicEmpty.hidden = true;
    tbody.append(dynamicEmpty);

    let page = 1;
    let pageRows = 25;
    let filteredRows = allRows.slice();
    let sortIndex = -1;
    let sortDirection = 1;

    const externalSearch = table.id === 'direction-statistics-table' ? document.getElementById('direction-search') : null;
    const directionMode = table.id === 'direction-statistics-table' ? document.getElementById('direction-filter') : null;
    const directionPresets = table.id === 'direction-statistics-table' ? Array.from(document.querySelectorAll('[data-direction-preset]')) : [];
    const directionSelect = table.id === 'event-statistics-table'
      ? document.getElementById('event-direction-filter')
      : (table.id === 'decline-statistics-table' ? document.getElementById('decline-direction-filter') : null);

    const matchesSpecificFilter = (row) => {
      if (table.id === 'direction-statistics-table' && directionMode) {
        const visits = Number(row.dataset.visits || 0);
        const events = Number(row.dataset.events || 0);
        const members = Number(row.dataset.members || 0);
        const mode = directionMode.value;
        if (mode === 'active' && visits <= 0 && events <= 0) return false;
        if (mode === 'inactive' && (visits > 0 || events > 0)) return false;
        if (mode === 'visits' && visits <= 0) return false;
        if (mode === 'no-visits' && visits > 0) return false;
        if (mode === 'events' && events <= 0) return false;
        if (mode === 'members' && members <= 0) return false;
      }
      if (directionSelect && directionSelect.value !== 'all') {
        const ids = String(row.dataset.directionIds || '').split(',').filter(Boolean);
        if (!ids.includes(directionSelect.value)) return false;
      }
      return true;
    };

    const parseValue = (value) => {
      const cleaned = String(value || '').replace(/\u00a0/g, ' ').replace(/[%\s]/g, '').replace(',', '.');
      if (cleaned && /^-?\d+(\.\d+)?$/.test(cleaned)) return Number(cleaned);
      return normalize(value);
    };

    const update = () => {
      const query = normalize(search ? search.value : (externalSearch ? externalSearch.value : ''));
      filteredRows = allRows.filter((row) => matchesSpecificFilter(row) && (!query || safeText(row).includes(query)));
      if (sortIndex >= 0) {
        filteredRows.sort((left, right) => {
          const a = parseValue(left.cells[sortIndex]?.textContent || '');
          const b = parseValue(right.cells[sortIndex]?.textContent || '');
          const cmp = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'ru', { numeric: true, sensitivity: 'base' });
          return cmp * sortDirection;
        });
      }
      pageRows = Number(pageSize.value) || 25;
      const pages = Math.max(1, Math.ceil(filteredRows.length / pageRows));
      page = Math.min(Math.max(1, page), pages);
      allRows.forEach((row) => { row.hidden = true; });
      const offset = (page - 1) * pageRows;
      const visibleRows = filteredRows.slice(offset, offset + pageRows);
      visibleRows.forEach((row) => { row.hidden = false; tbody.insertBefore(row, dynamicEmpty); });
      // Keep the server-rendered empty state when the report has no directions;
      // use the interactive empty state only when filters/search hide real rows.
      originalEmptyRows.forEach((row) => { row.hidden = allRows.length > 0; });
      dynamicEmpty.hidden = allRows.length === 0 || filteredRows.length !== 0;
      count.textContent = `Найдено: ${filteredRows.length}`;
      const legacyCount = document.getElementById(table.id === 'direction-statistics-table' ? 'direction-filter-count' : (table.id === 'event-statistics-table' ? 'event-direction-filter-count' : (table.id === 'decline-statistics-table' ? 'decline-direction-filter-count' : '')));
      if (legacyCount) legacyCount.textContent = `Показано: ${filteredRows.length} из ${allRows.length}`;
      pagerInfo.textContent = filteredRows.length
        ? `${offset + 1}–${offset + visibleRows.length} из ${filteredRows.length}`
        : 'Нет строк';
      pager.hidden = filteredRows.length <= pageRows;
      prev.disabled = page <= 1;
      next.disabled = page >= pages;
      table.querySelectorAll('thead th').forEach((header, index) => {
        header.classList.toggle('stats-sort-active', index === sortIndex);
        header.setAttribute('aria-sort', index === sortIndex ? (sortDirection === 1 ? 'ascending' : 'descending') : 'none');
        const label = header.dataset.sortLabel || header.innerText.trim();
        header.title = `Сортировать по столбцу «${label}»`;
        header.setAttribute('aria-label', `${label}. Нажмите для сортировки`);
        header.tabIndex = 0;
        header.classList.add('stats-sortable');
      });
    };

    const sortBy = (index) => {
      if (sortIndex === index) sortDirection *= -1;
      else { sortIndex = index; sortDirection = 1; }
      page = 1;
      update();
    };
    table.querySelectorAll('thead th').forEach((header, index) => {
      header.addEventListener('click', () => sortBy(index));
      header.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sortBy(index); }
      });
    });

    if (search) search.addEventListener('input', () => { page = 1; update(); });
    if (externalSearch) {
      externalSearch.addEventListener('input', () => { page = 1; update(); });
      externalSearch.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && externalSearch.value) {
          externalSearch.value = '';
          page = 1;
          update();
        }
      });
      document.addEventListener('keydown', (event) => {
        const target = event.target;
        const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
        if (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
          event.preventDefault();
          externalSearch.focus();
        }
      });
    }
    if (pageSize) pageSize.addEventListener('change', () => { page = 1; update(); });
    const syncDirectionPresets = () => {
      if (!directionMode) return;
      directionPresets.forEach((button) => {
        const active = button.dataset.directionPreset === directionMode.value;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
      });
    };
    if (directionMode) directionMode.addEventListener('change', () => { page = 1; syncDirectionPresets(); update(); });
    directionPresets.forEach((button) => button.addEventListener('click', () => {
      if (!directionMode) return;
      directionMode.value = button.dataset.directionPreset || 'all';
      page = 1;
      syncDirectionPresets();
      update();
    }));
    syncDirectionPresets();
    if (directionSelect) directionSelect.addEventListener('change', () => { page = 1; update(); });
    const localReset = table.id === 'direction-statistics-table' ? document.getElementById('direction-local-reset') : null;
    if (localReset) localReset.addEventListener('click', () => {
      if (externalSearch) externalSearch.value = '';
      if (directionMode) directionMode.value = 'all';
      syncDirectionPresets();
      page = 1;
      if (externalSearch) externalSearch.focus();
      update();
    });
    prev.addEventListener('click', () => { page -= 1; update(); });
    next.addEventListener('click', () => { page += 1; update(); });

    exportButton.addEventListener('click', () => {
      const headers = Array.from(table.querySelectorAll('thead th')).map((cell) => cell.innerText.trim());
      const csvCell = (value) => {
        let safe = String(value || '').replace(/\r?\n/g, ' ').trim();
        if (/^[\t ]*[=+@-]/.test(safe)) safe = `'${safe}`; // prevent spreadsheet formula injection
        return `"${safe.replace(/"/g, '""')}"`;
      };
      const lines = [headers.map(csvCell).join(';')];
      filteredRows.forEach((row) => lines.push(Array.from(row.cells).map((cell) => csvCell(cell.textContent)).join(';')));
      const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${table.id || 'statistics'}-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });

    update();
  });
})();
