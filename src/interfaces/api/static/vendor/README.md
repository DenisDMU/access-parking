# Bibliothèques tierces servies par Access

Le dashboard n'appelle aucun CDN : la clé d'exploitation est saisie dans
cette page, donc tout script qu'elle charge vient d'Access lui-même.

| Fichier | Bibliothèque | Version | Licence | SHA-256 |
|---|---|---|---|---|
| `three-0.160.0.module.min.js` | [three.js](https://threejs.org) (paquet npm `three`, `build/three.module.min.js`) | 0.160.0 (r160) | MIT | `3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6` |

Empreinte vérifiée identique sur deux sources (jsDelivr et unpkg) le
24/11/2026, et recontrôlée par `tests/integration/test_dashboard.py` : le
fichier ne peut pas être modifié sans faire échouer la CI. Utilisée par
`parking3d.js` (onglet « Plan 3D »).
