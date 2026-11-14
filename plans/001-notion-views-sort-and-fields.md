# Plan 001: Fix Notion DB view sorts, visible properties, empty groups, and stale quick-filter

> **Executor instructions**: Follow this plan step by step. Run every verification check and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: Fetch database `e072f4c04bbf467793879e7dce4e4373` via Notion MCP `notion-fetch` and verify the 4 view URIs and JSON configurations below still match before updating any view.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx (Notion UX / configuration)
- **Planned at**: commit `7c2707a` (`bot-ops` / `shared`), `2026-11-15`

## Why this matters

Currently all 4 views on the Notion database **每日情报归档与决策看板** (`e072f4c04bbf467793879e7dce4e4373`) lack proper sorting or hide the `类型` field. Because `🏷️ 信源分类` and `📊 按周看板` have no `sorts`, cards appear in insertion order—verified live where `2026-11-12` rows render before `2026-11-14`, and backfilled `2026-11-11` (`🗽 美股与加密`) sits at the bottom. Additionally, `🏷️ 信源分类` carries a dangling empty quick-filter, `📊 按周看板` displays an empty `2026-W45` column, `📅 日历打卡` hides `类型` (`开盘前瞻` vs `收盘复盘`) while cramming long `30秒速览` text into narrow day cells, and `Default view` lacks a secondary sort and a bounded "recent" filter.

## Current state

Live `notion-fetch` output for database `e072f4c04bbf467793879e7dce4e4373` (`collection://e1052ed6-a74e-4029-9396-499280ad5f2d`) shows these 4 views:

1. `Default view` (`view://f23a0293-26da-4a07-948d-92ec7c78e113`):
   ```json
   {"columnWidths":{"30秒速览":209,"信源":182,"周次":165,"日期":225,"标题":292,"类型":167},"dataSourceUrl":"collection://e1052ed6-a74e-4029-9396-499280ad5f2d","displayProperties":["标题","30秒速览","信源","周次","日期","类型"],"name":"Default view","sorts":[{"direction":"descending","property":"日期"}],"type":"table"}
   ```
2. `📅 日历打卡` (`view://41618b4d-66e9-81d4-88b7-000cb2f6caab`):
   ```json
   {"calendarBy":"日期","dataSourceUrl":"collection://e1052ed6-a74e-4029-9396-499280ad5f2d","displayProperties":["信源","30秒速览","标题"],"name":"📅 日历打卡","type":"calendar"}
   ```
3. `📊 按周看板` (`view://41618b4d-66e9-8130-977a-000c663bbceb`):
   ```json
   {"cardLayoutMode":"default","dataSourceUrl":"collection://e1052ed6-a74e-4029-9396-499280ad5f2d","displayProperties":["信源","日期","30秒速览","标题"],"fullWidthProperties":[],"groupBy":{"hideEmptyGroups":false,"property":"周次","propertyType":"select","sort":{"type":"manual"}},"name":"📊 按周看板","type":"board"}
   ```
4. `🏷️ 信源分类` (`view://41618b4d-66e9-81b8-8a0b-000c120fc576`):
   ```json
   {"cardLayoutMode":"default","dataSourceUrl":"collection://e1052ed6-a74e-4029-9396-499280ad5f2d","displayProperties":["日期","周次","30秒速览","标题"],"fullWidthProperties":[],"groupBy":{"hideEmptyGroups":false,"property":"信源","propertyType":"select","sort":{"type":"manual"}},"name":"🏷️ 信源分类","simpleFilters":[{"filter":{"operator":"enum_is","property":"信源","propertyType":"select","type":"property","value":{"type":"exact"}},"id":"f577fb1b-6de4-4b58-be5b-661dc5c58c41"}],"type":"board"}
   ```

Schema property names (exact): `标题`, `30秒速览`, `信源`, `周次`, `日期`, `类型`.

## Tools you will need

| Purpose | Tool / Action | Expected on success |
|---|---|---|
| Inspect views | Notion MCP `notion-fetch` (`id="e072f4c04bbf467793879e7dce4e4373"`) | Returns `<views>` JSON matching Current state |
| Update view | Notion MCP `notion-update-view` (`view_id`, `configure`) | Updates view JSON; `notion-fetch` reflects change |
| Create view | Notion MCP `notion-create-view` (`database_id`, `data_source_id`, `name`, `type`, `configure`) | Creates new view tab under database |
| Verify ordering | Notion MCP `notion-query-data-sources` (`data.mode="view"`, `data.view_url=...`) | Newest date appears first within each view/group |

## Scope

**In scope** (Notion database views only):
- View `view://f23a0293-26da-4a07-948d-92ec7c78e113` (`Default view`)
- View `view://41618b4d-66e9-81b8-8a0b-000c120fc576` (`🏷️ 信源分类`)
- View `view://41618b4d-66e9-8130-977a-000c663bbceb` (`📊 按周看板`)
- View `view://41618b4d-66e9-81d4-88b7-000cb2f6caab` (`📅 日历打卡`)
- New rolling table view `🗓️ 近7日速览` on database `e072f4c04bbf467793879e7dce4e4373`

**Out of scope**:
- Do NOT edit or delete any page rows in `collection://e1052ed6-a74e-4029-9396-499280ad5f2d`.
- Do NOT modify database schema columns (`30秒速览`, `信源`, `周次`, `日期`, `类型`, `标题`) — schema extensions belong to separate product direction work.
- Do NOT modify any local Python/shell files in `~/.gemini/bots/`.

## Git workflow

No git changes required (Notion remote configuration only). Still update the status row in `plans/README.md` if acting standalone without a reviewer maintaining the index.

## Steps

### Step 1: Fix `🏷️ 信源分类` (`view://41618b4d-66e9-81b8-8a0b-000c120fc576`)

First fetch `notion://docs/view-dsl-spec` via MCP `read_resource` (or `notion-fetch`) to confirm exact `CLEAR QUICK FILTER`, `GROUP BY`, `SORT BY`, and `SHOW` syntax.
Then call `notion-update-view`:
- `view_id`: `"view://41618b4d-66e9-81b8-8a0b-000c120fc576"`
- `configure`:
  `CLEAR QUICK FILTER; GROUP BY "信源" HIDE EMPTY; SORT BY "日期" DESC, "类型" ASC; SHOW "标题", "日期", "类型", "30秒速览", "周次"`
(If the DSL rejects `HIDE EMPTY` or multi-column `SORT BY`, apply the single-column DSL `CLEAR QUICK FILTER; SORT BY "日期" DESC; SHOW "标题", "日期", "类型", "30秒速览"` and confirm `GROUP BY` hide-empty flag separately.)

**Verify**: Run `notion-query-data-sources` with `{"data": {"mode": "view", "view_url": "https://app.notion.com/p/e072f4c04bbf467793879e7dce4e4373?v=41618b4d-66e9-81b8-8a0b-000c120fc576", "is_archived": false}}` -> within `🗽 美股与加密` and `🤖 AI 产业日报`, `2026-11-14`/`2026-11-13` appear BEFORE `2026-11-12` and `2026-11-11`; `notion-fetch` on the view shows `simpleFilters` removed, `sorts` non-empty, and `"类型"` in `displayProperties`.

### Step 2: Fix `📊 按周看板` (`view://41618b4d-66e9-8130-977a-000c663bbceb`)

Call `notion-update-view`:
- `view_id`: `"view://41618b4d-66e9-8130-977a-000c663bbceb"`
- `configure`:
  `GROUP BY "周次" HIDE EMPTY; SORT BY "日期" DESC, "信源" ASC, "类型" ASC; SHOW "标题", "信源", "类型", "日期", "30秒速览"`

**Verify**: Call `notion-fetch` on `view://41618b4d-66e9-8130-977a-000c663bbceb` -> `groupBy.hideEmptyGroups` is `true`, `sorts` starts with `{"direction": "descending", "property": "日期"}`, and `displayProperties` includes `"类型"`. Call `notion-query-data-sources` in `view` mode -> `2026-11-14` cards precede `2026-11-12` cards.

### Step 3: Fix `📅 日历打卡` (`view://41618b4d-66e9-81d4-88b7-000cb2f6caab`)

Calendar cells have narrow vertical height; showing `30秒速览` wraps/truncates heavily while hiding `类型` makes two `📈 A股与港股` cards on the same day look identical.
Call `notion-update-view`:
- `view_id`: `"view://41618b4d-66e9-81d4-88b7-000cb2f6caab"`
- `configure`:
  `SHOW "标题", "信源", "类型"`

**Verify**: Call `notion-fetch` on `view://41618b4d-66e9-81d4-88b7-000cb2f6caab` -> `displayProperties` contains `["标题", "信源", "类型"]` (or `["信源", "类型", "标题"]`), without `30秒速览`.

### Step 4: Tighten `Default view` and add a rolling `🗓️ 近7日速览` table view

1. Update `Default view` (`view://f23a0293-26da-4a07-948d-92ec7c78e113`) to sort deterministically on same-day rows (`日期` DESC, then `信源` ASC, then `类型` ASC) and widen `30秒速览` from `209` px to at least `420` px so decision signals remain readable without opening every row:
   - `view_id`: `"view://f23a0293-26da-4a07-948d-92ec7c78e113"`
   - `configure`: `SORT BY "日期" DESC, "信源" ASC, "类型" ASC; WIDTH "标题" 260, "30秒速览" 440, "信源" 150, "类型" 110, "日期" 140, "周次" 110`
2. Create a bounded rolling view `🗓️ 近7日速览` (`table`) via `notion-create-view` so daily reading stays fast even as total archived rows grow to hundreds/thousands:
   - `database_id`: `"e072f4c04bbf467793879e7dce4e4373"`
   - `data_source_id`: `"collection://e1052ed6-a74e-4029-9396-499280ad5f2d"`
   - `name`: `"🗓️ 近7日速览"`
   - `type`: `"table"`
   - `configure`: first verify exact relative-date `FILTER` syntax in `notion://docs/view-dsl-spec` (e.g., past week filter on `"日期"`), plus `SORT BY "日期" DESC, "信源" ASC, "类型" ASC; SHOW "标题", "30秒速览", "信源", "类型", "日期"; WIDTH "标题" 260, "30秒速览" 440`.

**Verify**: Call `notion-fetch` on `e072f4c04bbf467793879e7dce4e4373` -> all 5 views present, `Default view` has multi-column sort and widened `30秒速览`, and `🗓️ 近7日速览` filters active rows to the recent 7-day window (test with `notion-query-data-sources` in `view` mode).

## Done criteria

- [ ] `🏷️ 信源分类` (`view://41618b4d-66e9-81b8-8a0b-000c120fc576`) has `sorts` descending by `日期`, includes `类型`, hides empty groups, and has zero dangling empty `simpleFilters`.
- [ ] `📊 按周看板` (`view://41618b4d-66e9-8130-977a-000c663bbceb`) has `hideEmptyGroups: true`, `sorts` descending by `日期`, and includes `类型`.
- [ ] `📅 日历打卡` (`view://41618b4d-66e9-81d4-88b7-000cb2f6caab`) displays `类型` instead of full `30秒速览`.
- [ ] `Default view` (`view://f23a0293-26da-4a07-948d-92ec7c78e113`) has deterministic secondary sort (`信源`, `类型`) and widened `30秒速览` column.
- [ ] New `🗓️ 近7日速览` view exists and returns only recent 7-day rows when queried via `notion-query-data-sources`.

## STOP conditions

Stop and report back (do not improvise) if:
- `notion://docs/view-dsl-spec` is unreachable or `notion-update-view` rejects a DSL directive repeatedly after one syntax retry (do NOT drop `GROUP BY` on board views — Notion rejects board views without `GROUP BY`).
- Database `e072f4c04bbf467793879e7dce4e4373` already had views renamed/deleted since the drift check.
- Modifying `Calendar` or `Board` `displayProperties` errors on property name mismatch.

## Maintenance notes

- Note from `notion-update-view` documentation: for `select` properties (`信源`, `周次`), omit `BY OPTION` / `BY GROUP` inside `GROUP BY`.
- When Plan `004` improves `30秒速览` to front-load signals and highlights, `Default view` and `🗓️ 近7日速览` (`440px` width) will immediately show decision status without truncation.
