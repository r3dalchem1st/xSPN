/*
 * Collapsible bracket columns, shared by every xSPN page with a Bracket tab
 * (World Cup, leagues, cups). A column whose matches are all already
 * decided is rendered pre-collapsed (class "br-col done collapsed") with
 * its title marked role="button"/tabindex="0" -- this script just toggles
 * "collapsed" on click or Enter/Space.
 *
 * Uses event delegation on `document` rather than querying/attaching a
 * listener per title element, so it works identically whether the bracket
 * markup already exists at load time (leagues/cups, server-rendered) or is
 * built later by page JS (the World Cup page's client-side bracket render).
 */
(function () {
  function toggle(title) {
    var col = title.parentElement;
    var collapsed = col.classList.toggle('collapsed');
    title.setAttribute('aria-expanded', String(!collapsed));
  }

  document.addEventListener('click', function (e) {
    var title = e.target.closest('.br-col.done > .br-title');
    if (title) toggle(title);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var title = e.target.closest('.br-col.done > .br-title');
    if (!title) return;
    e.preventDefault();
    toggle(title);
  });
})();
