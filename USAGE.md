# Satellite Tracker 🛰️

My Satellite Tracker is a desktop app that shows you which satellites fly over any place on Earth in the next 48 hours. It also tells you if you can really see them in the night sky, just with your eyes and no telescope.

---

## Contents

1. [Why we built it](#why-we-built-it)
2. [How NASA helps our app](#how-nasa-helps-our-app)
3. [How to install it](#how-to-install-it)
4. [How to use it](#how-to-use-it)
5. [When can you see a satellite?](#when-can-you-see-a-satellite)
6. [Challenges we had](#challenges-we-had)
7. [Where the data comes from](#where-the-data-comes-from)
8. [Troubleshooting](#troubleshooting)
9. [What we learned](#what-we-learned)

---

## Why we built it

Did you know you can see the International Space Station (ISS) from your garden? It looks like a very bright star that moves across the sky in a few minutes. Most people never notice it, because they don't know **when** and **where** to look.

That is why we built this app. We wanted a program where you just click on your location and it tells you:

- which satellites fly over you,
- at what time,
- in which direction you have to look,
- and if you can actually see them (it has to be dark, the satellite has to be in sunlight, and there should not be too many clouds).

We are also really interested in space, and we wanted to learn how real data from NASA and other space organisations works. A project like this was a good way to learn Python, GUIs and a bit of physics at the same time.

## How NASA helps our app

NASA is the American space agency, and a lot of its data is free for everyone. Our app uses NASA data in three places:

1. **Satellite photos (NASA Worldview / VIIRS):** When you choose a location, the app downloads a real satellite photo of that area from **yesterday**. It comes from the VIIRS camera on the satellite *Suomi NPP*, which takes a picture of the whole Earth every day. You can see clouds, deserts, forests and snow on it.
2. **The Earth on the 3D globe (NASA Blue Marble):** The 3D view uses NASA's famous "Blue Marble" picture as the texture for the Earth, so it looks like the real planet.
3. **Positions of the Sun and Moon (NASA JPL):** To know if it is dark and if a satellite is in sunlight, we need to know exactly where the Sun and the Moon are. For this we use the *DE421* data file from NASA's **Jet Propulsion Laboratory (JPL)**. It is the same kind of data NASA uses to plan space missions!

The orbits of the satellites themselves come from **CelesTrak**, a website that publishes the orbit data of the US Space Force for free.

## How to install it

You need **Python 3.11 or newer** and internet.

```bash
# optional: make a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install PyQt6 numpy matplotlib requests skyfield python-dotenv timezonefinder
```

Then start the app:

```bash
python main.py
```

The first start takes a bit longer, because the app downloads the orbit data and the JPL file (about 17 MB). After that it is fast.

## How to use it

### 1. Choose your location

When you start the app, you see a world map. There are three ways to pick a place:

| Way | What you do |
|---|---|
| **Click on the map** | Just click somewhere. The map is split into small squares (tiles), and when you move the mouse over one you see its coordinates. |
| **Use my current location** | Menu **Location → Use my current location** (or `Ctrl+L`). The app finds out roughly where you are (which city) from your internet connection. |
| **Search for a place** | Menu **Location → Search place...** (or `Ctrl+F`) and type a city or address. |

> **Privacy:** "Use my current location" sends your IP address to a website (ipinfo.io) to find your city. Nothing else is sent.

If you need it more exact, you can also type the latitude, longitude and height yourself in the next window and press **Use location**.

### 2. Look at the passes

A new window opens. On the left you see the satellite photo from NASA and a short summary. On the right is a table with all satellite passes for the next 48 hours.

| Column | What it means |
|---|---|
| ★ | A favourite: ISS, Hubble or the Chinese space station Tiangong |
| Satellite | The name of the satellite |
| Culmination | The time when it is highest in the sky (the best moment to look) |
| Mag | How bright it is (smaller number = brighter) |
| Max Alt | How high it gets above the horizon, in degrees |
| Clouds | Cloud forecast for that time |
| Visibility | Visible, Cloudy, Faint, Daylight, Earth shadow or Low pass |
| Duration | How long you can see it |

Click on a column title to sort the table.

### 3. Use the filters

| Filter | What it does |
|---|---|
| **Only visible** | Only shows satellites you can really see (on by default) |
| **Only favorites** | Only ISS, Hubble and Tiangong |
| **Moon glare** | Warns you when the bright Moon is close to the satellite |
| **Max Clouds** | Hides passes with too many clouds |
| **Max Mag** | Hides satellites that are too faint |
| **Search** | Search by name or number |
| **Reset** | Puts all filters back to normal |

You can also change the **time zone** at the top: the time of the place, your own computer time, or UTC.

### 4. Look at the details

When you click on a pass, you see everything about it, for example:

- **when** it rises, is highest, and sets,
- **where** to look (like "rises in the NW, highest in the S"),
- how bright it is, how far away and how fast (often about 7 km per **second**!),
- where the Sun and Moon are,
- and the cloud forecast.

### 5. 3D globe

Press **Open 3D globe** to see the orbit on a 3D Earth. Red is the whole orbit, yellow is the part you can see, cyan is the path on the ground, and green is you. You can turn the Earth with the mouse and zoom with the mouse wheel.

### 6. Save the results

Press **Export CSV** to save all passes that are shown in the table as a `.csv` file. You can open it in Excel or Google Sheets. (Tip for German Excel: use **Data → From Text/CSV**, otherwise everything ends up in one column.)

### Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+L` | Use my current location |
| `Ctrl+F` | Search place |
| `F1` | Help |
| `Ctrl+Q` | Quit |

## When can you see a satellite?

This was one of the most interesting things we learned. Satellites don't have their own light. You only see them because they **reflect sunlight**, like the Moon. So our app checks five things:

1. **High enough:** at least **10°** above the horizon, otherwise trees and houses are in the way.
2. **Dark for you:** the Sun has to be **below the horizon** where you are.
3. **Sunny for the satellite:** the satellite must **not be in Earth's shadow**. It is up to 400 km high or more, so it can still be in sunlight when it is already night for you.
4. **Bright enough:** the brightness (magnitude) has to be **+3.5 or brighter**.
5. **Not too cloudy:** the cloud cover has to be **under 50 %**.

Because of points 2 and 3, the best time is usually **1–2 hours after sunset or before sunrise**. In the middle of the night, most satellites are in Earth's shadow and you can't see them.

### What does "magnitude" mean?

Astronomers measure brightness with *magnitude*. It works the opposite way to what you'd expect: **smaller numbers are brighter**.

| Magnitude | How it looks |
|---|---|
| under −1 | Super bright (the ISS can reach about −3!) |
| −1 to +1 | Very bright, even in a city |
| +1 to +3.5 | Easy to see when it is dark |
| over +3.5 | Hard to see, better use binoculars |

## Challenges we had

Building this app was harder than we thought. Here are the biggest problems and how we solved them:

**1. Calculating where a satellite is.**
Satellite orbits are described with "TLE" data: two lines full of numbers. We could not calculate orbits from that ourselves, so we used the Python library **Skyfield**, which does the hard physics. But we still had to understand what azimuth, altitude and culmination mean.

**2. Is the satellite visible or not?**
At first we only checked if the satellite is above the horizon, and the app showed hundreds of passes that you could never see in real life. We had to learn about Earth's shadow, twilight and brightness to make it realistic. Estimating the brightness was the hardest part, because it depends on the size of the satellite, the distance and the angle of the sunlight.

**3. The app was really slow.**
At first the world map was made of almost **5,000 single buttons**. Starting the app took long, and moving the windows was laggy. We changed it so the whole map is drawn as **one picture**, and the app now finds out which square you clicked from the mouse position. Calculating the passes was also slow (about 9 seconds), because we did the Sun and Moon calculations for every pass one by one. Now we do them for all passes at once, and it takes **less than one second**.

**4. A bug that only happened on Windows.**
One day the app suddenly found **zero satellites**. The reason was hard to find: Windows saves line endings differently, and when we saved the orbit data, every line got an extra invisible character. Skyfield then could not read the file anymore. A tiny invisible character broke the whole app!

**5. Time zones.**
A pass at "19:30" means nothing if you don't know which time zone it is. We had to find the time zone for every place on Earth and let the user switch between local time, their own time and UTC.

**6. Keeping the app responsive.**
Downloading data and calculating passes takes time. If you do that in the main program, the window freezes. We learned to use **background threads**, so the window keeps working and shows a progress bar.

**7. Not downloading everything again and again.**
The free websites don't like it if you ask them too often. So we save (cache) the data on the computer: the orbit data is only downloaded again after 6 hours, and calculated passes are reused within the same hour.

## Where the data comes from

| Data | Source |
|---|---|
| Satellite orbits | CelesTrak |
| Satellite photos | NASA Worldview (VIIRS) |
| Earth texture for 3D | NASA Blue Marble |
| Sun and Moon positions | NASA JPL (DE421) through Skyfield |
| Satellite brightness | McCants quicksat list |
| Cloud forecast, height, place search | Open-Meteo |
| Your current location | ipinfo.io |

All the data is saved in the folders `sat_cache/` and `map_tiles/`. You can delete them anytime; the app will just download everything again.

## Troubleshooting

| Problem | What to do |
|---|---|
| "No TLE data received" | Check your internet. If it still doesn't work, delete the `.tle` files in `sat_cache/` and restart. |
| No passes shown | Untick **Only visible** or press **Reset**. In summer in the north, it sometimes doesn't get dark enough. |
| Times are one hour wrong | Install `timezonefinder`, or switch the time zone to *Local* or *UTC*. |
| "Location not found" | Try again later or use **Search place** instead. |
| "Could not load NASA image" | The NASA website is sometimes slow. The rest of the app still works. |

## What we learned

- How satellites move and why you can only see them at certain times
- How to use real scientific data from NASA, JPL and CelesTrak
- How to build a program with windows and buttons (PyQt6)
- That making a program **fast** is just as important as making it work
- That one invisible character can break everything, and how to find bugs like that
- How to use background threads so the program doesn't freeze


