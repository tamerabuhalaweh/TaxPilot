(function () {
  var paths = {
    dashboard:
      '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    clients:
      '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c.4-3.2 2.6-5.1 5.5-5.1s5.1 1.9 5.5 5.1"/><path d="M16 5.2a3 3 0 0 1 0 5.6M17.5 14.9c2 .5 3.2 2.2 3.5 4.6"/>',
    reviews:
      '<path d="M6 3.5h9l3 3v14H6z"/><path d="M15 3.5v3h3M9 11h6M9 15h6"/>',
    reports:
      '<path d="M4 4h16v16H4z"/><path d="M8 16v-5M12 16V8M16 16v-3"/>',
    settings:
      '<circle cx="12" cy="12" r="3.2"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M18 6l-1.4 1.4M7.4 16.6 6 18"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
    file: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12h6M9 16h4"/>',
    shield:
      '<path d="M12 3 20 6v6c0 4.4-3.2 7.6-8 9-4.8-1.4-8-4.6-8-9V6z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
    globe:
      '<circle cx="12" cy="12" r="8.5"/><path d="M3.8 12h16.4M12 3.5c2.2 2.3 3.4 5.2 3.4 8.5s-1.2 6.2-3.4 8.5c-2.2-2.3-3.4-5.2-3.4-8.5S9.8 5.8 12 3.5Z"/>',
    spark:
      '<path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z"/><path d="m18.5 16 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    alert: '<path d="M12 4 21 20H3z"/><path d="M12 9v5M12 17.2v.1"/>',
    logout: '<path d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10"/>',
    document: '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M10 13h5M10 16.5h5"/>',
    play: '<path d="m9 6 9 6-9 6z"/>',
    chevron: '<path d="m8 10 4 4 4-4"/>',
    download: '<path d="M12 4v11M8 11l4 4 4-4M5 19h14"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5H5V6h5"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    user: '<circle cx="12" cy="8" r="3.4"/><path d="M4.5 20c.5-3.6 3.2-5.7 7.5-5.7s7 2.1 7.5 5.7"/>',
    building:
      '<path d="M4 21V4h10v17M14 9h6v12M7 8h4M7 12h4M7 16h4M17 13h1M17 17h1"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
    filter: '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5z"/><path d="M4 5.5v13M8 7h8M8 11h8"/>',
    eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/><circle cx="12" cy="12" r="2.6"/>'
  };

  function renderIcon(el) {
    var name = el.getAttribute("data-icon");
    var path = paths[name];
    if (!path) return;
    el.classList.add("icon");
    el.setAttribute("aria-hidden", "true");
    el.innerHTML =
      '<svg viewBox="0 0 24 24" width="100%" height="100%" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="display:block">' +
      path +
      "</svg>";
  }

  function init() {
    var nodes = document.querySelectorAll("[data-icon]");
    for (var i = 0; i < nodes.length; i += 1) renderIcon(nodes[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
