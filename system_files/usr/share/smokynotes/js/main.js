// Point d'entrée : bibliothèque ↔ éditeur.
import { initLibrary, showLibrary } from './library.js';
import { initEditor, openEditor } from './editor.js';

initEditor(() => showLibrary());
initLibrary((id) => openEditor(id));
showLibrary();
