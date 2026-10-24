# Satellite Tracker

I built a desktop app that shows you which satellites will fly over any place on Earth in the next 48 hours and if you are able to see them with your own eyes.

![Satellite Tracker – pass list for a selected location](assets/Detailedview.png)

**[ Download the latest release](https://github.com/javinwittig/satelite_tracker/releases/latest)**

---

## Quick start

Download the version for your system from the [releases page](https://github.com/javinwittig/satelite_tracker/releases/latest), unpack it, start `SatelliteTracker`, and click anywhere on the world map. No Python needed.

| System | File |
|---|---|
| Windows (64-bit) | `SatelliteTracker-windows-x64.zip` |
| Linux (64-bit) | `SatelliteTracker-linux-x64.tar.gz` |
| macOS (Apple Silicon, M1 and newer) | `SatelliteTracker-macos-arm64.zip` |

- **Windows:** the app is not signed, so Windows may show "Windows protected your PC". Click More info and then Run anyway.
- **macOS:** the app is not signed either, so macOS blocks it the first time you open it. Go to *System Settings → Privacy & Security*, scroll down and click *Open Anyway*. If macOS says the app is damaged, run `xattr -cr SatelliteTracker.app` in the Terminal and try again.
- **Linux:** some distributions also need the `libxcb-cursor0` package.
- Downloaded data (orbits, weather, images) is cached in `~/.satellite_tracker`.


## Features

You pick a location by clicking on the world map. You can also search for a place or type in the coordinates and elevation yourself.

The app then lists all passes of about 170 bright satellites over the next 48 hours, including the ISS, Hubble and Tiangong. Rise, peak and set times are shown in the local time of that place.

For each pass it checks if you can actually see it. The sky has to be dark, the satellite has to be lit by the sun, it has to be bright enough and there shouldn't be too many clouds. If one of these doesn't fit, the app shows you which one.

There's also:

- an estimated brightness (magnitude) for every pass
- the cloud forecast for the time of the pass, and a note when the moon is bright and close to the satellite's path
- filters for visible passes, favorites, cloud cover and brightness, plus a search by name or NORAD ID
- a 3D globe with the satellite's path and a NASA satellite photo of the area

![3D globe view of a satellite pass](assets/3D-view.png)


## How it works

The Orbit data for the satellites comes from CelesTrak. My app stores the orbit data for six hours before it downloads the orbit data again because predictions become less accurate as orbit data gets older. Using this orbit data Skyfield works out every pass that climbs at ten degrees above the horizon. Passes that stay below ten degrees are generally blocked by buildings or trees.

Satellites do not glow by themselves. You can only spot a satellite when the sun shines on it and it is already dark where you are. Therefore, for each pass the app verifies that the sun's at least six degrees below your horizon and that the bright satellite is outside Earth’s shadow. If either of these conditions fails the bright satellite will be invisible.

Brightness of a satellite varies from one pass to another so the app recalculates brightness each time. It begins with the bright satellite’s brightness listed in the McCants Quicksat catalogue. Then it adjusts that brightness for distance sunlight angle and the amount of air the light must travel when the bright satellite is low. If the resulting brightness is brighter than magnitude three point five the bright satellite is considered visible to the eye even in a city.

For weather the app retrieves hourly cloud cover from Open-Meteo. It then takes the cloud cover for the hour when the bright satellite reaches its point in the sky.

The world map is divided into around five thousand tiles. Each tile carries its latitude and longitude. This design lets you click anywhere, on the map without requiring a map library.
## Credits

- [CelesTrak](https://celestrak.org) — satellite orbit data
- [Skyfield](https://rhodesmill.org/skyfield/) by Brandon Rhodes — orbit and astronomy calculations
- [Open-Meteo](https://open-meteo.com) — cloud forecast and place search
- [NASA Worldview / GIBS](https://worldview.earthdata.nasa.gov) — satellite imagery and the Blue Marble Earth texture
- [Mike McCants' Quicksat](https://www.mmccants.org) — standard satellite magnitudes
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)

**AI usage:** I used [opencode](https://opencode.ai) sometimes when I was stuck on a problem and couldn't continue otherwise.
