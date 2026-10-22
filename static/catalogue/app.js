(() => {
  'use strict';
  const back = document.getElementById('back-selection');
  back?.addEventListener('click', () => { if (history.length > 1) history.back(); else location.assign('/'); });
  const viewSwitch = document.getElementById('archive-view-switch');
  if (viewSwitch) {
    const buttons = [...viewSwitch.querySelectorAll('[data-archive-view]')];
    const listView = document.getElementById('archive-list');
    const treeView = document.getElementById('archive-tree');
    const preferenceKey = 'sersi-notices.archive-view';
    const setView = mode => {
      listView.hidden = mode === 'tree';
      treeView.hidden = mode !== 'tree';
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.archiveView === mode)));
    };
    let preferred = 'list';
    try { if (localStorage.getItem(preferenceKey) === 'tree') preferred = 'tree'; } catch {}
    setView(preferred);
    viewSwitch.hidden = false;
    buttons.forEach(button => button.addEventListener('click', () => {
      setView(button.dataset.archiveView);
      try { localStorage.setItem(preferenceKey, button.dataset.archiveView); } catch {}
    }));
  }
  const form = document.getElementById('selection-form');
  if (!form) return;
  const rows = [...form.querySelectorAll('[data-product]')];
  const system = document.getElementById('id_systeme');
  const brand = document.getElementById('id_marque');
  const search = document.getElementById('product-search');
  const category = document.getElementById('category-filter');
  const inactive = document.getElementById('include-inactive');
  const selectAll = document.getElementById('select-visible');
  const brandOptions = [...brand.options];
  const categoryOptions = [...category.options];
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
  function matchesSystem(row) {
    return (!system.value || row.dataset.systems.split(' ').includes(system.value)) &&
      (inactive.checked || row.dataset.active === '1');
  }
  function eligible(row) {
    return matchesSystem(row) &&
      (!brand.value || row.dataset.brand === brand.value || row.dataset.generic === '1');
  }
  function restrictOptions(select, options, available) {
    const selected = select.value;
    select.replaceChildren(...options.filter(option => !option.value || available.has(option.value)));
    select.value = available.has(selected) ? selected : '';
  }
  function update() {
    const systemRows = rows.filter(matchesSystem);
    restrictOptions(brand, brandOptions, new Set(systemRows.map(row => row.dataset.brand)));
    const brandRows = systemRows.filter(eligible);
    restrictOptions(category, categoryOptions, new Set(brandRows.map(row => row.dataset.category)));
    let visible = 0;
    const query = normalize(search.value.trim());
    rows.forEach(row => {
      const allowed = eligible(row);
      if (!allowed) row.querySelector('input').checked = false;
      row.hidden = !allowed || (category.value && row.dataset.category !== category.value) || !normalize(row.dataset.search).includes(query);
      if (!row.hidden) visible++;
    });
    form.querySelectorAll('.product-group').forEach(group => {
      const children = [...group.querySelectorAll('[data-product]')].filter(row => !row.hidden);
      group.hidden = !children.length;
      group.querySelector('.group-count').textContent = children.length;
    });
    const selected = rows.filter(row => row.querySelector('input').checked).length;
    document.getElementById('selected-count').textContent = selected;
    document.getElementById('visible-count').textContent = `${visible} produit${visible > 1 ? 's' : ''}`;
    document.getElementById('no-results').hidden = visible > 0;
    const shown = rows.filter(row => !row.hidden);
    const checkedShown = shown.filter(row => row.querySelector('input').checked).length;
    selectAll.checked = shown.length > 0 && checkedShown === shown.length;
    selectAll.indeterminate = checkedShown > 0 && checkedShown < shown.length;
    selectAll.disabled = !shown.length;
    const hasTypes = [...form.querySelectorAll('[name="types_export"]')].some(input => input.checked);
    document.getElementById('prepare-button').disabled = !selected || !hasTypes;
  }
  [system, brand, category, inactive].forEach(input => input.addEventListener('change', update));
  search.addEventListener('input', update);
  form.addEventListener('change', event => { if (event.target.name === 'produits' || event.target.name === 'types_export') update(); });
  selectAll.addEventListener('change', () => { rows.filter(row => !row.hidden).forEach(row => { row.querySelector('input').checked = selectAll.checked; }); update(); });
  document.getElementById('clear-selection').addEventListener('click', () => { rows.forEach(row => { row.querySelector('input').checked = false; }); update(); });
  window.addEventListener('pageshow', update);
  update();
})();
