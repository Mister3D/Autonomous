# Export discussion PDF

**Status**: in place  
**Key files**: `autonomous/services/chat_export.py`, `autonomous/pdf_text.py`, `autonomous/api/bots.py`, `frontend/src/components/ManageMenu.vue`, `autonomous/assets/fonts/DejaVuSans*.ttf`  
**Last updated**: 2026-11-05 (frontend via `vite build` / `serve --dev` watch)

## User behaviour

- Panneau Détails → actions → **Exporter en PDF**.
- Titre **Discussion**, même langage visuel que le fil : séparateurs de jour, bulles (vous à droite en bleu, assistant à gauche en gris), horaires à côté.
- Groupes d’outils = même carte que `.tool-group` (ouvert) : `⚙ N outils` + badge (`TERMINÉ` / `N ERREUR(S)`) + heure, puis chaque ligne `nom · TERMINÉ/ERREUR · HH:MM` — **sans** args ni résultats. Teinte done / error / running comme l’UI.
- Les outils « silencieux » de l’UI (`memory_*`, `ask_clarify`, mail interne, etc.) n’apparaissent pas.
- Cartes coffre / mémoire / approval / etc. → pastille centrée, pas le détail.

## Implementation

- `GET /api/v1/bots/:name/messages/export.pdf` → `application/pdf` (pièce jointe).
- `list_all_messages` pagine `list_messages` jusqu’à tout le fil.
- `transcript_blocks` → `build_discussion_pdf` (`pdf_text.ChatPdf` + polices DejaVu).

## Pitfalls / non-regressions

- Ne jamais coller `meta.args` / corps de résultat d’outil dans le PDF.
- Secrets / vault : pas de contenu sensible (résumé de carte seulement).

## Quick check

```bash
python3 -m pytest tests/test_chat_export.py -q

curl -s -b cookies -o /tmp/d.pdf -D - \
  http://127.0.0.1:8787/api/v1/bots/<slug>/messages/export.pdf | head
file /tmp/d.pdf
```
