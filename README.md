# Satellite Tracker

I built a desktop app that shows you which satellites will fly over any place on Earth in the next 48 hours and if you are able to see them with your own eyes.

![Satellite Tracker – pass list for a selected location](assets/Detailedview.png)

**[⬇️ Download the latest release](https://github.com/javinwittig/satelite_tracker/releases/latest)**

---

## Quick start

Download the version for your system from the [releases page](https://github.com/javinwittig/satelite_tracker/releases/latest), unpack it, start `SatelliteTracker`, and click anywhere on the world map. No Python needed.

| System | File |
|---|---|
| Windows (64-bit) | `SatelliteTracker-windows-x64.zip` |
| Linux (64-bit) | `SatelliteTracker-linux-x64.tar.gz` |
| macOS (Apple Silicon, M1 and newer) | `SatelliteTracker-macos-arm64.zip` |

- **Windows:** the app is not signed, so Windows may show "Windows protected your PC". Click *More info* and then *Run anyway*.
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

The orbit data for the bright satellites comes from [CelesTrak](https://celestrak.org). The app saves it for 6 hours and then downloads it again, because the predictions get less accurate the older the data is. With that data, [Skyfield](https://rhodesmill.org/skyfield/) calculates every pass that gets at least 10° above the horizon. Anything lower is usually hidden behind buildings or trees anyway.

Satellites don't glow by themselves. You can only see one when the sun is shining on it while it's already dark where you are. So for each pass the app checks if the sun is at least 6° below your horizon and if the satellite is outside of Earth's shadow at that moment. If either one isn't true, you won't see it.

How bright a satellite looks changes from pass to pass, so the app calculates it every time. It starts with the satellite's standard brightness from the McCants Quicksat catalogue and adjusts it for the distance, the angle of the sunlight and how much air the light has to go through when the satellite is low. If it comes out brighter than magnitude 3.5, it counts as visible with the naked eye, even in a city.

For the weather, the app gets the hourly cloud cover from [Open-Meteo](https://open-meteo.com) and uses the hour when the satellite is highest in the sky.

The world map is split into about 5,000 small tiles, and each one has its own latitude and longitude. That's how you can click anywhere on the map without needing a map library.

## Credits

- [CelesTrak](https://celestrak.org) — satellite orbit data
- [Skyfield](https://rhodesmill.org/skyfield/) by Brandon Rhodes — orbit and astronomy calculations
- [Open-Meteo](https://open-meteo.com) — cloud forecast and place search
- [NASA Worldview / GIBS](https://worldview.earthdata.nasa.gov) — satellite imagery and the Blue Marble Earth texture
- [Mike McCants' Quicksat](https://www.mmccants.org) — standard satellite magnitudes
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) and [Matplotlib](https://matplotlib.org) — UI and 3D globe

**AI usage:** I used [opencode](https://opencode.ai) sometimes when I was stuck on a problem and couldn't continue otherwise.
