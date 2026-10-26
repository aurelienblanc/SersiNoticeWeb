(() => {
  'use strict';
  const form = document.getElementById('document-search-form');
  if (!form) return;
  const brand = form.querySelector('[name="marque"]');
  const suggestions = document.getElementById('document-references');
  const options = [...suggestions.options];
  const updateSuggestions = () => {
    suggestions.replaceChildren(
      ...options.filter((option) => !brand.value || option.dataset.brand === brand.value),
    );
  };
  brand.addEventListener('change', updateSuggestions);
  window.addEventListener('pageshow', updateSuggestions);
  updateSuggestions();
})();
