# Columbia Gas of Ohio for Home Assistant

A [HACS](https://hacs.xyz/) custom integration that logs into the Columbia
Gas of Ohio customer portal (`myaccount.columbiagasohio.com`) with your own
account credentials and brings gas usage and billing data into Home
Assistant -- including the Energy dashboard.

This is not affiliated with, endorsed by, or supported by Columbia Gas of
Ohio or NiSource. It's an independent integration built by reverse-
engineering the public customer portal; see
[Known limitations](#known-limitations) below.

If this integration is useful to you, you're welcome to
[support its development](https://buy.stripe.com/4gM28t6SP0aLdTx29Z1Jm00) --
entirely optional, never required to use it.

## What you get

- One sensor for your gas meter showing current cumulative usage
  (`device_class: gas`, `state_class: total_increasing`, unit Ccf).
- Full historical monthly usage -- as far back as the portal's usage-history
  export retains (about 24 months, confirmed) -- imported into Home
  Assistant's long-term statistics, so it shows up correctly in
  **Settings -> Dashboards -> Energy** once you add the gas statistic there.
- One sensor with your most recent bill amount, due date, billing period,
  days in the billing period, and cost per day as attributes. The service
  address and account holder's name are **not** shown unless you turn on
  *Show service address and account holder* in the integration's options:
  attributes are saved in Home Assistant's history database and can be read
  by dashboards, voice assistants and other integrations.
- Bill amounts are also imported as a long-term statistic (running total
  billed, one point per billing period) so bill cost is graphable
  month-over-month via a Statistics Graph card or Developer Tools ->
  Statistics -- not just visible as the latest bill's sensor state.

**Note on granularity:** unlike some utility portals, Columbia Gas of Ohio's
customer portal exposes no hourly or daily advanced-meter data anywhere --
monthly meter reads are the finest granularity available (confirmed during
development by walking every account/usage/billing page on a real account).
So there's no polling-frequency tradeoff to make here: the portal's own data
only advances once a month regardless of how often this integration checks.

## Installation (HACS custom repository)

1. In Home Assistant, open **HACS -> Integrations -> ⋮ -> Custom
   repositories**.
2. Add this repository's URL, category **Integration**.
3. Install "Columbia Gas of Ohio" from HACS, then restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration**, search for
   "Columbia Gas of Ohio", and enter the username/password you use to log
   in at `myaccount.columbiagasohio.com`.

Credentials are stored using Home Assistant's built-in config entry storage
(encrypted at rest) -- this integration never writes its own credential
storage, and never logs credential values, even at debug level.

## Polling

Every sync fetches the portal's full retained usage/billing history in one
request each (no chunking needed -- the portal itself only returns ~24
months, not a windowed range) and imports whatever is newer than what Home
Assistant already has. Data is fetched once every 24 hours by default,
configurable at **Settings -> Devices & services -> Columbia Gas of Ohio ->
Configure**. Changing it reloads the integration and applies immediately --
no restart needed.

## Known limitations

- **Bill billing-period start dates are approximate**, same caveat as the
  usage history: the billing-history export has no explicit period-start
  column; it's inferred from the previous bill's date (or 30 days back, for
  the oldest bill fetched).
- **This integration scrapes a portal-internal CSV export**, not a
  documented API -- if Columbia Gas changes the portal, syncing can break
  until the integration is updated. Debug logging is verbose by design to
  make that easy to diagnose and report.
- Built and tested against one real, single-account Columbia Gas login;
  multi-account logins are not yet handled (see `client/accounts.py`'s
  module docstring for what that would need).
- No custom brand icon yet (Home Assistant/HACS will show a generic default
  icon until one is added) -- deferred, see Fast-follow below.

## Testing

`tests/client/` (portal scraping/parsing, no Home Assistant dependency) runs
anywhere, including Windows:

```
uv sync
uv run pytest tests/client/ -v
```

`tests/ha/` (coordinator, config flow, sensors -- needs a real `hass`
fixture) only runs on Linux; see [tests/README.md](tests/README.md) for why
and how it's kept separate. CI (`.github/workflows/test.yml`) runs both on
every push.

## Fast-follow (deliberately deferred from v1)

- An original (non-infringing) brand icon for HACS/HA, mirroring how
  `ha-westerville-utilities/brands/` was built for its sibling integration.
- Multi-account login support.

## Related projects

- [`utility-reader`](https://github.com/prajwal-skdlove/utility-reader) --
  this integration's Columbia Gas client code was ported from this
  local-first CLI, which syncs the same data into a SQLite database. Its
  `PLAN.md` documents how the portal's login flow and CSV export endpoints
  were originally reverse-engineered.
- [`ha-westerville-utilities`](https://github.com/prajwal-skdlove/ha-westerville-utilities) --
  the sibling integration this one's architecture (client/coordinator/
  config_flow/sensor split, external-statistics import pattern, test
  structure) was mirrored from, for a different (electric/water) utility
  portal.

## License

MIT -- see [LICENSE](LICENSE).
