/*
 * Shared tab-bar behaviour for every xSPN competition page. Replaces the
 * per-template `function show(n){...}` (an inline onclick handler matching
 * a hardcoded tab-name array by position) that was copy-pasted into every
 * template's own <script> block. This version is generic -- it reads the
 * tablist/tabpanel structure straight from the DOM (role + aria-controls),
 * so it needs no per-page tab-name list, and adds the keyboard support the
 * old onclick-only version never had (WAI-ARIA "tabs" pattern: arrow keys
 * move + activate, Home/End jump to the first/last tab).
 */
(function () {
  function activate(tabs, target, focusTarget) {
    tabs.forEach(function (tab) {
      var selected = tab === target;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
      tab.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(tab.getAttribute('aria-controls'));
      if (panel) panel.classList.toggle('active', selected);
    });
    if (focusTarget) target.focus();
  }

  function initTablist(tablist) {
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));
    if (!tabs.length) return;
    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { activate(tabs, tab, false); });
      tab.addEventListener('keydown', function (e) {
        var next = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = tabs[(i + 1) % tabs.length];
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = tabs[(i - 1 + tabs.length) % tabs.length];
        else if (e.key === 'Home') next = tabs[0];
        else if (e.key === 'End') next = tabs[tabs.length - 1];
        if (next) { e.preventDefault(); activate(tabs, next, true); }
      });
    });
  }

  document.querySelectorAll('[role="tablist"]').forEach(initTablist);
})();
