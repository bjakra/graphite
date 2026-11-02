# Plan: Graphite Weather, a private weather provider

Goal: give the lock screen (the Weather clock face and the smartspace line) real weather, without Google,
without an account or API key, and with location use that each user explicitly chooses.

Status: implemented, apart from the setup wizard step. Tested on the emulator with a manual location, device location and weather switched off; not yet on the phone.

## How weather reaches the lock screen

```
GraphiteWeather app (WeatherProvider, content://org.graphite.weather.data/current)
  → GraphiteWeather hook in SystemUI (patch 0470), on change and after unlock
  → KeyguardUpdateMonitor.sendWeatherData → clock.events.onWeatherDataChanged
```

SystemUI's smartspace session only starts with Google's data plugin, so a `SmartspaceService` can't deliver this.
The provider is only readable with `STATUS_BAR_SERVICE`, which means SystemUI. With weather off the provider is
empty and nothing is sent, so the Weather clock shows no temperature rather than a false 0°. A reading already
sent stays on the clock until SystemUI restarts, because there is no call to clear it.

## Components

**`GraphiteWeather` app** (own repo, `packages/apps/GraphiteWeather`): `WeatherClient` fetches and parses,
`WeatherStore` caches, `RefreshJobService` refreshes through `JobScheduler` while on a network, and the settings
page lives in the app (Settings → System → Graphite → Weather), so GraphiteParts needs no internet access.

## Settings

| Setting | Values | Default |
|---|---|---|
| Weather | Off / On | **Off** |
| Location source | Manual / Device location | Manual |
| Manual location | City search, or latitude and longitude | none |
| Units | Follow system / °C / °F | Follow system |
| Refresh interval | 1, 2, 4 or 6 hours | 2 hours |
| Provider | Open-Meteo / MET Norway | Open-Meteo |

With weather off, the app makes no network requests and holds no location.

## Location

**Manual (default).** The user types a city and picks a result, or enters coordinates. Only the search text
goes to the geocoding service, and only when the user searches. Entering coordinates uses no network at all.

**Device location (opt-in).** Enabled only by an explicit choice on the settings page, which explains what is
sent where, followed by the normal Android permission prompt.

* `ACCESS_COARSE_LOCATION` only. Never fine or background location.
* A one-shot read while the settings page is open, or when the user taps "Update location". With coarse permission
  the fused provider only asks network location, which GrapheneOS leaves off by default, so GPS is used when network
  location is off. There is no background tracking. The refresh job reuses the saved position. Updating it automatically would need
  background location, so that is a separate, later decision.
* If the permission is revoked, weather falls back to the last saved position and the page says so.

## Security and privacy

* **Small attack surface.** The app parses untrusted JSON from the network, so it gets the fewest permissions
  possible: `INTERNET` and, only if chosen, coarse location. It isn't privileged. It is platform signed so its
  provider can be limited to SystemUI's permission.
* **Coordinates are rounded** to 2 decimals (about 1 km) before they leave the phone, and requests carry no
  identifiers, cookies or user-specific headers.
* **TLS only**, using the system trust store, with a size limit and strict validation on responses. An
  unknown weather code maps to "no weather" rather than a crash.
* **Storage:** location and settings stay in credential encrypted storage, so they can't be read before the
  first unlock, and are excluded from backups. The app isn't direct boot aware, and SystemUI reads it again after unlock.
* **GrapheneOS controls keep working.** Revoking the Network permission just stops updates and weather expires.
  The Sensors and location toggles apply as normal.
* **What the provider sees:** your IP address and rounded position at each refresh. That can't be avoided
  without a proxy, so the settings page says it plainly. Only one provider is contacted at a time.

## Providers

| | Open-Meteo | MET Norway |
|---|---|---|
| API key | None | None, needs an identifying User-Agent |
| Coverage | Global | Global |
| Geocoding | Yes | No, so it would still use Open-Meteo's geocoding or coordinates |
| Licence | CC BY 4.0, shown in the About section | CC BY 4.0, shown in the About section |

Open-Meteo is the proposed default. Its free tier is for non-commercial use, which needs checking if Graphite is
ever distributed widely. Its API returned "service is overloaded" during this research, so a second provider
is a real requirement. Failures keep the cached value until it expires, and never retry in a tight loop.

## Setup wizard (later)

Add one step to `packages/apps/SetupWizard2`: **Off**, **Enter a location**, or **Use device location**. It writes
the same settings as the settings page and can be skipped. The default is Off, so skipping sends nothing. The
wizard links to the page rather than duplicating logic.

## Still open

Add the setup wizard step above. Decide whether Lawnchair's At a Glance should show this weather too; Smartspacer doesn't
compete for anything here, because weather no longer goes through the smartspace service.
