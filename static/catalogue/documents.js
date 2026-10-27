(() => {
  'use strict';
  const form = document.getElementById('document-search-form');
  if (!form) return;
  const brand = form.querySelector('[name="marque"]');
  const select = form.querySelector('[name="reference"]');
  const picker = form.querySelector('.document-product-picker');
  const input = document.getElementById('document-product-search');
  const list = document.getElementById('document-product-options');
  const status = document.getElementById('document-product-status');
  const options = [...select.options];
  const normalize = (text) =>
    text
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();
  let allowed = [];
  let visible = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };
  const activate = (index) => {
    active = index;
    [...list.children].forEach((item, position) =>
      item.classList.toggle('is-active', position === active),
    );
    const item = list.children[active];
    if (item) {
      input.setAttribute('aria-activedescendant', item.id);
      item.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  };
  const choose = (option) => {
    select.value = option.value;
    input.value = option.value ? option.textContent : '';
    input.setCustomValidity('');
    status.classList.add('sr-only');
    status.textContent = '';
    close();
  };
  const show = () => {
    const query = select.value ? '' : normalize(input.value.trim());
    visible = allowed.filter(
      (option) => !query || (option.value && normalize(option.textContent).includes(query)),
    );
    // Exact references precede similarly named variants when using the keyboard.
    if (query)
      visible.sort(
        (a, b) => Number(normalize(b.value) === query) - Number(normalize(a.value) === query),
      );
    const items = visible.map((option, index) => {
      const item = document.createElement('li');
      item.id = `document-product-option-${index}`;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(option.value === select.value));
      item.dataset.value = option.value;
      const reference = document.createElement('strong');
      reference.textContent = option.value || 'Tous les produits';
      item.append(reference);
      if (option.dataset.description) {
        const description = document.createElement('span');
        description.textContent = option.dataset.description;
        item.append(description);
      }
      return item;
    });
    list.replaceChildren(...items);
    if (!items.length) {
      close();
      status.classList.remove('sr-only');
      status.textContent = 'Aucun produit trouvé.';
      return;
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    status.classList.add('sr-only');
    status.textContent = `${visible.filter((option) => option.value).length} produit(s) proposé(s).`;
    activate(visible.findIndex((option) => option.value === select.value));
  };
  const updateBrand = () => {
    const previous = select.value;
    allowed = options.filter(
      (option) => !option.value || !brand.value || option.dataset.brand === brand.value,
    );
    select.replaceChildren(...allowed);
    const selected = allowed.find((option) => option.value === previous);
    choose(selected || allowed[0]);
  };

  input.addEventListener('focus', show);
  input.addEventListener('click', show);
  input.addEventListener('input', () => {
    select.value = '';
    input.setCustomValidity('');
    if (input.value.trim()) show();
    else choose(allowed[0]);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (list.hidden) show();
      if (visible.length) {
        const step = event.key === 'ArrowDown' ? 1 : -1;
        activate(
          active < 0
            ? step > 0
              ? 0
              : visible.length - 1
            : (active + step + visible.length) % visible.length,
        );
      }
    } else if (event.key === 'Enter' && !list.hidden) {
      event.preventDefault();
      if (visible.length) choose(visible[Math.max(active, 0)]);
    } else if (event.key === 'Escape') {
      if (!list.hidden) event.preventDefault();
      close();
    } else if (event.key === 'Tab') close();
  });
  list.addEventListener('mousedown', (event) => event.preventDefault());
  list.addEventListener('click', (event) => {
    const item = event.target.closest('[role="option"]');
    if (item) choose(visible.find((option) => option.value === item.dataset.value));
  });
  document.addEventListener('pointerdown', (event) => {
    if (!picker.contains(event.target)) close();
  });
  brand.addEventListener('change', updateBrand);
  window.addEventListener('pageshow', updateBrand);
  form.addEventListener('submit', (event) => {
    if (input.value.trim() && !select.value) {
      event.preventDefault();
      input.setCustomValidity('Choisissez un produit dans la liste, ou effacez la recherche.');
      input.reportValidity();
    }
  });

  updateBrand();
  select.hidden = true;
  picker.querySelector('.product-combobox').hidden = false;
  form.querySelector('label[for="id_reference"]').htmlFor = input.id;
})();
