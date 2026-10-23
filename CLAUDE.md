# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Inventory control system ("Sistema de Estoque") for Avance Construtora, built on Django 6.1 with the **django-unfold** admin theme. There are no public views. The whole app is the Django admin (`/` redirects to `admin:index`). Code, models, UI strings and commit messages are in **Portuguese (pt-BR)**. Keep that convention.

## Commands

Windows dev environment with a local `venv/`:

```powershell
venv\Scripts\Activate.ps1
pip install -r requirements.txt          # file is UTF-16 encoded (pip freeze from PowerShell)
python manage.py runserver
python manage.py makemigrations stock    # or accounts
python manage.py migrate
python manage.py test                    # all tests (stock/tests.py and accounts/tests.py are still empty)
python manage.py test stock.tests.SomeTestCase.test_method
```

### Settings

- `manage.py` defaults to `core.settings.production`. For local work, use `--settings=core.settings.development` or set `DJANGO_SETTINGS_MODULE`.
- `core/settings/settings.py` is the shared base (apps, UNFOLD config, i18n). `production.py` and the local, untracked `development.py` both `from .settings import *` and override DEBUG/hosts/DB.
- Both environments use **PostgreSQL** and read config from `.env` via python-dotenv (see `exemplo.env` for the keys). `ALLOWED_HOSTS` must be set or settings import crashes (`.split` on None).
- `settings.py` still declares a SQLite `DATABASES`. It is dead config because both environment files override it.
- Gotcha: `.gitignore` lists `development.py` by bare name, so a new file with that name anywhere in the repo gets ignored.
- Gotcha: `core/wsgi.py` and `core/asgi.py` point at `core.settings`, which is a package without a settings module, not at `core.settings.production`. Set `DJANGO_SETTINGS_MODULE` explicitly when deploying.
- `BASE_DIR` resolves to `core/` (not the repo root), so `TEMPLATES["DIRS"]` and `STATICFILES_DIRS` mean `core/templates` and `core/static`.

## Architecture

### Apps
- **`stock`**: all domain models (one model per file in `stock/models/`, re-exported from `stock/models/__init__.py`. Add new models there too) and all their ModelAdmins in `stock/admin.py`.
- **`accounts`**: `Perfil` (OneToOne to `User`, M2M to `Filial`, plus `cargo`). Its admin re-registers `User`/`Group` with Unfold forms and shows `Perfil` as an inline on the user page.
- **`core`**: project package with settings, urls, `dashboard.py`, and template overrides for `admin/index.html` (dashboard) and `admin/login.html`.

### Domain model (inventory flow)
`Filial` (branch) + `Produto` → `Estoque` (unique per produto+filial, has `quantidade_minima` alert threshold) → `Lote` (stock-entry batch with NF, price, `quantidade_entrada`, and `quantidade_atual` = remaining balance). **Stock quantity is never stored on `Estoque`.** It is always the sum of `Lote.quantidade_atual`.

Stock leaves a lote in three ways. Each one copies `produto` and the unit price from the lote at write time (non-editable fields), so history keeps the price that applied then:
- **`AplicacaoEstoque`**: applied to a specific `Equipamento`.
- **`ConsumoGeral`**: general use with a free-text `finalidade`. This is deliberately a copy of AplicacaoEstoque's logic.
- **`TransferenciaEstoque`**: moves stock between branches with a `pendente → confirmada | cancelada` workflow. Creating it does **not** touch stock. `confirmar_transferencia()` deducts from the source lote and creates a new `Lote` (and `Estoque` if missing) at the destination with the same cost/NF.

Balance-changing logic lives in model `save()`/`delete()`, not in the admin. The calls use `transaction.atomic()` + `select_for_update()` on the lote. Editing restores the old quantity to the old lote before deducting again, and deleting does a reversal (`estorno`). `clean()` checks the balance for form errors, and `save()` checks again under the lock. Because of this, **bulk deletes/`QuerySet.update()` bypass the stock bookkeeping**. The admins remove the `delete_selected` action for this reason. Keep that rule when adding movement types.

### Per-branch access control
Defined in `stock/admin.py` and reused across the app:
- `filiais_do_usuario(user)` returns `None` for superusers (meaning all branches), the user's `Perfil.filiais` otherwise, and an empty queryset if the user has no Perfil.
- `FiltroPorFilialMixin` + `campo_filial = "<path to filial>"` filters admin querysets.
- `formfield_for_foreignkey` overrides limit lote/estoque/filial choices to the user's branches. `LoteComSaldoMixin` hides empty lotes (but keeps the currently saved one on edit). `LoteAdmin.get_search_results` does the same for autocomplete, keyed by `model_name`. Add new movement models to that tuple.
- Transfers: the source branch edits/deletes while pending, and only the **destination** branch (or a superuser) can confirm. Confirm/cancel exist both as list actions and Unfold `actions_detail` buttons.

### Admin UI / dashboard
- The sidebar navigation is hand-defined in `UNFOLD["SIDEBAR"]` in `core/settings/settings.py` (`show_all_applications: False`). **New admin pages must be added there** or they won't appear in the menu.
- `core/dashboard.py:dashboard_callback` (wired via `UNFOLD["DASHBOARD_CALLBACK"]`) builds the cards, Chart.js data (passed as JSON strings) and tables for `core/templates/admin/index.html`, using only Unfold components. It respects the user's branches through `filiais_do_usuario`. (Comments in the template still say `stock.dashboard`. The real path is `core.dashboard`.)
- Money and number formatting goes through `formatar_reais` (stock/admin.py) and `_numero_br` (dashboard), in Brazilian format.

## Conventions

- Commit messages: gitmoji + conventional type, in Portuguese, e.g. `:sparkles: feat: Adiciona ...`, `:fire: chore: Remove ...`.
- Models use Portuguese `verbose_name`s. Explanatory comments are written in Portuguese.
