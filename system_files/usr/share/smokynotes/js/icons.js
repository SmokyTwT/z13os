// Icônes au trait (24×24), dessinées pour Smoky Notes.
const P = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  import: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M5 17v2.5h14V17"/>',
  back: '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
  pages: '<rect x="4" y="4" width="6.5" height="7" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="7" rx="1.5"/><rect x="4" y="14" width="6.5" height="6" rx="1.5"/><rect x="13.5" y="14" width="6.5" height="6" rx="1.5"/>',
  pen: '<path d="M4 20l1.2-4.3L15.8 5.1a2 2 0 012.9 0l.2.2a2 2 0 010 2.9L8.3 18.8z"/><path d="M13.8 7.1l3.1 3.1"/>',
  highlighter: '<path d="M9 14l-3 3v2.5h4l2.5-2.5"/><path d="M9 14l6.8-8.6a1.8 1.8 0 012.6-.2l1.4 1.4a1.8 1.8 0 01-.2 2.6L11 16z"/><path d="M4 21h16" opacity=".5"/>',
  eraser: '<path d="M8.5 19.5L4.2 15.2a1.8 1.8 0 010-2.5l8.6-8.6a1.8 1.8 0 012.5 0l4.6 4.6a1.8 1.8 0 010 2.5L12 19.5z"/><path d="M8 9.5l6.5 6.5M8.5 19.5H20"/>',
  lasso: '<path d="M7 16.5C4.6 15.3 3.5 13.6 3.5 11.5 3.5 7.4 7.6 4.5 12 4.5s8.5 2.9 8.5 7-4.1 6.5-8.5 6.5c-1 0-2-.1-2.9-.4"/><circle cx="7.5" cy="17.5" r="2"/><path d="M6.5 19.3c-.3 1-1 1.7-2 2.2"/>',
  shape: '<rect x="3.5" y="10.5" width="9" height="9" rx="1.5"/><circle cx="15.5" cy="8.5" r="5"/>',
  text: '<path d="M5 6.5V5h14v1.5M12 5v14M9 19h6"/>',
  laser: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
  image: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M4 17l5-4.5 3.5 3 3-2.5 4.5 4"/>',
  undo: '<path d="M9 7L4.5 11.5 9 16"/><path d="M5 11.5h9.5a5 5 0 010 10H12"/>',
  redo: '<path d="M15 7l4.5 4.5L15 16"/><path d="M19 11.5H9.5a5 5 0 000 10H12"/>',
  finger: '<path d="M9 11V5.5a1.5 1.5 0 013 0V11"/><path d="M12 10.5V9a1.5 1.5 0 013 0v2"/><path d="M15 10.5a1.5 1.5 0 013 0V15a6 6 0 01-6 6h-.7a6 6 0 01-4.6-2.2L4.6 16a1.6 1.6 0 012.3-2.2L9 15.5"/>',
  more: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
  palette: '<path d="M12 3.5a8.5 8.5 0 100 17c1.2 0 1.8-.8 1.8-1.7 0-1.3-1.2-1.6-1.2-2.8 0-1 .8-1.6 1.8-1.6h2.2a3.9 3.9 0 003.9-3.9C20.5 6.6 16.7 3.5 12 3.5z"/><circle cx="7.8" cy="11" r="1.1"/><circle cx="10.5" cy="7.5" r="1.1"/><circle cx="15" cy="7.8" r="1.1"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6.5a2 2 0 00-2-2h-7a2 2 0 00-2 2v7a2 2 0 002 2h2"/>',
  duplicate: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M14 11.5v5M11.5 14h5M15.5 8.5V6.5a2 2 0 00-2-2h-7a2 2 0 00-2 2v7a2 2 0 002 2h2"/>',
  trash: '<path d="M4.5 7h15M10 4.5h4M6.5 7l.8 11.2a2 2 0 002 1.8h5.4a2 2 0 002-1.8L17.5 7"/><path d="M10 11v5M14 11v5"/>',
  star: '<path d="M12 4l2.4 5 5.4.7-4 3.7 1 5.4L12 16.2 7.2 18.8l1-5.4-4-3.7 5.4-.7z"/>',
  bookmark: '<path d="M7 4.5h10v15.5l-5-3.5-5 3.5z"/>',
  export: '<path d="M12 15V4M7.5 8.5L12 4l4.5 4.5"/><path d="M5 13v6.5h14V13"/>',
  edit: '<path d="M5 19l1-4 9.8-9.8a1.8 1.8 0 012.6 0l.4.4a1.8 1.8 0 010 2.6L9 18z"/>',
  template: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8 8h8M8 11.5h8M8 15h5"/>',
  zoomfit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  up: '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
  down: '<path d="M6.5 9.5L12 15l5.5-5.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v2.5"/>',
  listen: '<path d="M4.5 9.5h3l4-3.5v12l-4-3.5h-3z"/><path d="M15 9a4 4 0 010 6M17.5 6.5a7.5 7.5 0 010 11"/>',
  folder: '<path d="M3.5 7.5a2 2 0 012-2h4l2 2.5h7a2 2 0 012 2v7.5a2 2 0 01-2 2h-13a2 2 0 01-2-2z"/>',
};

export function icon(name, size = 22) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((el) => {
    if (!el.firstChild) el.innerHTML = icon(el.dataset.icon);
  });
}
