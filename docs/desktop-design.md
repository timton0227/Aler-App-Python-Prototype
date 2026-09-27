# Desktop design — the iPhone app's look, on Mac and Windows

The plan for Phase 14 in [`PROGRESS.md`](../PROGRESS.md). Steps 14.1 to 14.6 are built
(`alertmesh/style.py`, `phone_app.py`, `warning_app.py`); where the build differs from
this plan, [`CHANGELOG.md`](../CHANGELOG.md) says so. Step 14.7, the check on Windows, is
still open.

A clickable mockup of both apps, with a macOS / Windows switch, is in
[`desktop-design-mockup.html`](desktop-design-mockup.html). Open it in any browser.

All Swift paths are relative to `../alert-mesh/`.

## The idea

Both desktop apps, **Alert Mesh** (the phone app) and **Alert Mesh Warnings**, take the
iPhone app's own style:

- the system typeface;
- system blue for buttons and the selected tab;
- grey cards with 16-point rounded corners;
- a solid colour block only when a warning covers you;
- the red "I need help" bar;
- Messages-style chat bubbles.

The iPhone's bottom tab bar becomes a sidebar on the left, which is how Mac and Windows
apps show the same few tabs. The page inside the window is the same on both systems.
Only what the system owns follows the system: the window buttons, ⌘ or Ctrl, and the
order of buttons in a dialog.

## Rules taken from the iPhone app

Each rule is already written down in the Swift code, usually with its reason. The
desktop apps copy the rule, not just the look.

| iPhone rule | Swift | On the desktop |
|---|---|---|
| System typeface at every size; never monospace on emergency screens | `EmergencyType` in `AlertMesh/AlertMesh/Views/EmergencyLayout.swift` | SF Pro on Mac, Segoe UI Variable on Windows. No bundled font. |
| The accent colour is system blue | `ThemePalette.alertMesh` in `AlertMesh/Utils/Theme.swift` | `#007AFF` light, `#0A84FF` dark, on both systems (not the Windows accent colour) |
| Red means "leave now" and nothing else, except the call-for-help bar and calls for help | `alertRed`; `EmergencyHelpBarModifier` in `EmergencyRootView.swift` | Red only for Emergency Warnings, calls for help and the "I need help" bar |
| Only "a warning covers you" gets a solid colour block | `NowView.affectedBlock` | Top of Now. Every other warning is a grey card with a 6-point colour bar |
| A severity *fill* colour and a severity *text* colour are different | `severityAdviceText` and the others in `Theme.swift` | Level names on grey cards use the darker text colours, which reach 4.5:1 contrast |
| Cards: 16-point corners, 18-point padding, 16 points between blocks | `EmergencyLayout` | The same numbers |
| The level is shown by a symbol as well as by colour | `AlertSeverity.symbolName` in `AlertSeverityStyle.swift` | Circle-i for Advice, triangle for Watch and Act, octagon for Emergency Warning |
| Neighbours' hazard reports never borrow warning colours | `CommunityReportStyle.swift` | Hazard reports are grey. Only calls for help are red |
| "I need help" bar: 60 points tall, rounded, on a blurred bar at the bottom of Now | `EmergencyHelpBarModifier` | 56 points, pinned to the bottom of Now, with a keyboard shortcut |
| Chat bubbles: yours blue on the right, others grey on the left, 18-point corners | `ChatBubbleStyle` in `ChatBubbleRow.swift` | The same colours. Name above the first bubble of a run, time under the last |
| The connection in plain counts ("2 phones nearby can pass warnings to you") | `NowView.connectionSection` | The same card on Now, saying laptops. The status bar repeats it on every tab |

## Window and layout

```
┌─────────────────────────── title bar (the system's own) ───────────────────────────┐
│ Sidebar          │ Page title                                                      │
│  Now        2    │ ┌──────────────── main column ───────────────┐ ┌─ side column ─┐│
│  Report          │ │                                            │ │               ││
│  Chat       3    │ │                                            │ │               ││
│                  │ └────────────────────────────────────────────┘ └───────────────┘│
│                  │ ┌──────────────────── I need help (Now only) ─────────────────┐ │
│ you · town  ⚙    │ └─────────────────────────────────────────────────────────────┘ │
├──────────────────┴──────────────────────────────────────────────────────────────────┤
│ ● Bluetooth on · 2 laptops nearby   ● Local network on          Updated 10:42:05 am │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

- The window opens at **1200 × 760** and cannot be made smaller than **960 × 600**. That
  still fits a 1366 × 768 Windows laptop at 125% scaling (1093 × 614 usable). Today's
  smallest size, 700 × 600, is too narrow for a chat list beside a conversation.
- The sidebar is 220 wide. Below 1100 wide it shrinks to 76, showing icons with short
  labels under them, and side columns move under the main column.
- Unread and "for you" counts are red badges on the sidebar, as on the iPhone tab bar.
- Your nickname and town sit at the foot of the sidebar. Clicking them opens Settings.
- A status bar along the bottom shows Bluetooth and the local network on every tab. When
  one is off it says so and why.

## Screens

**Now** (the iPhone's `NowView`), top to bottom:

1. The status block. When a warning covers you, it is a solid block in the level's
   colour: symbol, level ("Emergency Warning"), "You are in this area", headline, hazard,
   end time, "Open full warning". Otherwise it is a grey card: "No current warnings" in
   the all-clear green, or "No warnings where you are".
2. "What to do": a card with a 2-point border in the level's colour, holding the
   instruction in large type.
3. Calls for help from people nearby, red-bordered, each with "Message" when that person
   is in range.
4. "Other warnings": grey cards with a colour bar, the level in its text colour, the
   headline, how far away and until when.
5. "How you're connected".

On a wide window, items 3 and 5 move to a side column. The "I need help" bar is pinned
below the page and opens the call-for-help sheet (the iPhone's `SOSView`). The sheet says
"This is not 000", and says the call for help carries the town picked in Settings, since
a laptop has no GPS.

**Report**: the form on the left (Type, How bad as three buttons with the iPhone's
symbols, the note), and "From people nearby" on the right. Calls for help are red; hazard
reports and "I'm safe" are grey. A line underneath says these are not official warnings
and nobody has checked them.

**Chat**: three panes, like Messages: sidebar, conversation list, conversation. The list
has "Chats" (Nearby first, then private conversations) and "People nearby". The
conversation header says who can read it. The message box is a rounded field with a round
blue send button. Return sends and Shift+Return starts a new line, on both systems.

**Warning app**: the same sidebar, with Console, Map and Hub board. The simulated clock
and its "+1 / +5 / +15 min" buttons move to the foot of the sidebar.
- **Console** (the Mac's `IssueWarningView`): the form on the left; on the right, a
  preview of the warning as phones show it, and the live warnings with Update…, Send
  again and a red Cancel warning. The result of each send appears at the top in today's
  wording.
- **Map**: as today, restyled.
- **Hub board**: stays black whatever the system theme, because it is shown on a
  projector in a hall.

## Mac and Windows

| Thing | macOS | Windows 11 | What we do |
|---|---|---|---|
| Window buttons | Top left | Top right | Keep the system's own window frame; never draw them |
| Typeface | SF Pro | Segoe UI Variable | The system face, like the iPhone app. Lines may wrap in slightly different places, so no layout may depend on exact text width |
| Shortcut key | ⌘ | Ctrl | Labels and hints change to match |
| Dialog buttons | Cancel, then the main button on the right | Main button first, then Cancel | The order changes to match. The main button is always the coloured one, and Return presses it |
| Menu bar | At the top of the screen | None | Every action has a button inside the window |
| Scrollbars | Hidden until you scroll | Always take space | Space is kept for them on both, so nothing shifts |
| Display scaling | 2× | 100% to 175% | Sizes in points. Check at 125% and 150% on Windows |
| Light and dark | System Settings | Personalisation | Follow the system on both, using the iPhone app's dark colours |

The page knows which system it is on from `sys.platform`: the page server runs on the
same computer as the window.

Dark mode changes a decision recorded in `.streamlit/config.toml`, which forces light
because the warning colours were light-theme colours and a projector reads dark text on
white best. The Swift palette now gives every warning colour a dark partner, and the Hub
board keeps its own black background, so both reasons are covered.

## Colours

From `Theme.swift`, `EmergencyLayout.swift` and `ChatBubbleRow.swift`. Light / dark.

| Use | Light | Dark |
|---|---|---|
| Accent (system blue) | `#007AFF` | `#0A84FF` |
| Page background | `#FFFFFF` | `#000000` |
| Card | `#F2F2F7` | `#1C1C1E` |
| Your chat bubble | `#0066DD` | `#0A6CFF` |
| Their chat bubble | `#E9E9EB` | `#26252A` |
| Emergency Warning fill, calls for help | `#BF1A1A` | `#BF1A1A` |
| Emergency Warning text | `#B01414` | `#FF6B6B` |
| Watch and Act fill / text | `#D16600` / `#9A3D00` | `#FF9426` / `#FF9E4D` |
| Advice fill / text | `#B88A00` / `#8A6200` | `#FFD633` / `#FFD84D` |
| All clear | `#1E7B34` | `#30D158` |

## Type

The iPhone uses text styles that grow with Dynamic Type. The desktop fixes them at about
88% of the iPhone's default size, because a laptop is read from further away but held
steady.

| Role (iPhone text style) | Desktop |
|---|---|
| Warning level (large title, heavy) | 30, heavy |
| What to do (title 2, semibold) | 20, semibold |
| Where you stand (title 3, semibold) | 18, semibold |
| Page title (title 2, bold) | 22, bold |
| Card headline (headline) | 16, semibold |
| Body | 15 |
| Section title (subheadline, bold, capitals) | 13, bold, capitals |
| Times and counts (subheadline) | 13.5 |

## Keyboard

| Action | macOS | Windows |
|---|---|---|
| Go to tab 1, 2, 3 | ⌘1, ⌘2, ⌘3 | Ctrl+1, Ctrl+2, Ctrl+3 |
| Settings | ⌘, | Ctrl+, |
| I need help (opens the sheet; sending takes a second press) | ⌘⇧H | Ctrl+Shift+H |
| Send a message | Return | Enter |
| Close a sheet | Esc | Esc |
| Hub board full screen | ⌃⌘F | F11 |

## Building it in Streamlit

With Streamlit 1.51, as installed.

| Piece | How | Effort |
|---|---|---|
| Colours, typeface, dark mode | Theme settings: the system font stack, a light and a dark colour set; drop `theme.base = "light"` from `.streamlit/config.toml` and `desktop.py` | Settings |
| Rounded cards, status block, colour bars | One stylesheet shared by both apps; cards drawn as small HTML blocks, as `warning_card` does today | Stylesheet |
| Sidebar with three tabs | Buttons in `st.sidebar`, styled; icon-only below 1100 wide | Stylesheet |
| "I need help" bar pinned at the bottom | A button in a container fixed to the bottom of the page | Stylesheet |
| Call-for-help sheet | `@st.dialog`, with the buttons ordered by `sys.platform` | Built in |
| Chat bubbles | Small HTML blocks instead of `st.chat_message`, whose avatars and layout do not match Messages | Stylesheet |
| Keyboard shortcuts | A few lines of script in the page | Small script |
| A live byte counter while typing | Not possible: `st.chat_input` does not report typing. Today's "at most 280 bytes" message after sending stays | Skipped |

## Risks

- Streamlit's own page structure can change between versions, and a stylesheet that
  targets it can break on an upgrade. `requirements.txt` should pin Streamlit to 1.51.x
  once the stylesheet exists, and the stylesheet should target as few of Streamlit's
  inner parts as possible.
- The Windows look is only checked in the mockup until a Windows PC is available
  (step 14.7, and 12.4 before it).
