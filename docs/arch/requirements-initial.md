# Agentic Live Music Calendar — Requirements

These are the screen-by-screen requirements of the initial version of Agentic Live Music Calendar

### Global Requirements

The UI will be responsive design and work across phone, tablet and desktop browsers. 

### Main Views & URL Scheme

Home page is a 4-week calendar, focused on today and next 4 weeks. (more on this below)

These are the main views:

* calendar = calendar views also save the filter settings (more on this below)
  * /day = a view focused on a particular day


* venue = shows all the meta data of a venue, editable. Has the default calendar lower in the page filtered to the venue
* artist = shows all the meta data of an artist, editable. Has the list view of calendar's upcoming shows
* show = consitutes a single live music event.

### Calendar (Including Home Page)

Calendar is the main function of this application.

By default, we see a vertically scrollable list of dates with horizontally scrollable group of venues. Each venue is a mini column of its own and can contain 1-2 shows.  Each show is represented as a block.

There is a header area where user can filter based on:

* Venue
* Artist
* Toggle for looking at past dates (later)
* Drop down for selecting the months. The months list is only future facing and contains only months for which we have shows in our DB.
* Genre (later)
* Text search/filter (later): I'm thinking of a text typing field that surfaces meta data values from all other fields -- indoor/outdoor, all ages, names of artist members

Venue and Artist filter will be a multi-select list with ability to type and filter down the items on the list.

Each show is represented as a block with the fields of the show. The focus is on the venue and the artist name.

If a particular filter selection returns empty results, the screen will say something like "No matches found" with an link/button to reset the filter.

Each day, venue and artist names are links. Clicking on the day will switch to the day view, clicking on the venue or artist name will go to the view dedicated to that entity. 

#### /Day view

A day view creates a vertical list of shows and allows the user to figure out how to view the list

* by Venue by alpha (default)
* by Venue by time
* by Artist by alpha

If the user chooses Venue mode, shows will be represented in blocks. If Artist mode is selected, then we create a list of Artist with the associated venue and time

### Venue

Venue page lists the meta data of a venue, which includes

* Venue name*
* Photo: link to a photo hosted elsewhere
* Address
* Phone number(s)
* Email(s)
* Website
* Social: a venue can associate many social accounts with the artist profile. We will also have a "type" of Social, which specifies whether it's Instagram, YouTube, Tik Tok, etc.
* Live Music Calendar URL of that venue*
* Age Restriction (All ages vs 21+)
* Serves alcohol (boolean)
* Type of venue (bar / club / theater / coffeehouse / arena / park / etc)
* Setting (indoor / outdoor / either or both)
* Seating (standing / seated / either or both)
* Metro: associated with a particular metro area

Venue page contains the default calendar filtered to that venue. But if user wants to do anything other than go back and forth to past or future with that exact calendar, they have to go to a calendar view page (navigates away from the Venue page)

Fields with * are the required ones for a venue

Any user can edit the fields, and save.

A user can also submit a new venue. We will need an AI workflow to review and try fetching their live music calendar. 

### Venues

Venues page is a simple listing of all venues. Clicking on a venue goes to the venue page. To start we will do a simple list sorted alphabetically by the venue name.

### Artist

Artist page lists the meta data of an artist, which includes

* Artist name*
* Genre: genre should be a tagging system, an artist can be tagged for multiple genres
* Photo: link to a photo hosted elsewhere
* Website
* Hometown: a free text field where a user can populate where the artist's homebase is. This is not a reference to a particular metro, even though the concept is similar
* Social: an artist can associate many social accounts with the artist profile. We will also have a "type" of Social, which specifies whether it's Instagram, YouTube, Tik Tok, etc.
* Format: solo, duo, trio, band (not necessarily the configuration of how the artist performs, more about the artist themselves. So a solo artist with a backing band still will be categorized as solo)
* Repertoire: original, cover or both/other. This is a fixed enum, not tags
* Members: an artist can have many members. A solo artist can have more than one members (could be a member of the backing band). Members should be a table of its own so that a person can be a member of multiple artists.
* Instrumentation: A multiselect list of instruments and their count (like guitar x2) there should be a table that feeds this list but users can add an instrument also (nice to have)

Artist page contains the list view of their upcoming shows.

### Artists

Similar to venues page, a simple listing of all artists. 

### Show

A "show" is a single live music event. It needs to be associated with one venue and one or more artists.

* Date*: a show must have a single date. Multi-day festival will be accommodated by Events
* Start Time
* End Time
* Venue: the venue of the show
* Artists: artist performing. One or more.

  * each artist can have its own time, which is the start time
  * each artist can also have sequence number, to note what order they are performing in the show
* The fields below are inherited by default from venue but can be overwritten. In the database they remain empty unless there is an input that is different from the parent venue

  * Age Restriction (All ages vs 21+)
  * Serves alcohol (boolean)
  * Setting (indoor / outdoor / either or both)
  * Seating (standing vs seated)
* Admission Advance: price of the admission when it's purchased in advance
* Admission Day: price of admission when it's purchased on the day of the show
* Free Admission: boolean. Can't be true and have either of Admission prices set. But we won't automtically assume this to true simply b/c neither Admission is filled out -- it may simply be missing info
* Image: a show could have like a poster. A link to an image hosted elsewhere
* original URL: the web page where this information was extracted. The most recent instance.

**Times after midnight** (Ari, October 10, 2026: must be handled; not with the 24+-hour "26:00" convention, which isn't
used in the US). **Decided (Ari, October 11, 2026):** a show belongs to the **night** the venue lists it
under — its Date — and a start or end time before **5:00 AM** is after midnight of that night. So a
listing under Friday at 1:00 AM is Friday night's show, sorted after Friday's evening shows and displayed with the
next day ("1:00 AM Sat"). An end time earlier than its start is the next morning (already the rule for validation).
No new fields: Date plus clock times plus the cutoff carry it. Some venues show the next calendar date for such times
(Mortimer's: "Oct 12, 9:00 PM – Oct 13, 2:00 AM"); others won't, so the agent must not depend on it.

**Possible enhancement — artists: display text and associations** (Ari, October 10, 2026; not adopted yet, to be
revisited before milestone A2.1 closes). A listing such as "ABC ft. DEF" names two artists, ABC and DEF, and the show
should be associated with both as Artist records — "ABC ft. DEF" must not become a third artist of its own. But the
show should still be *displayed* the way the venue wrote it, not as two names on separate lines. Proposal: a
`display_artists` field on the Show holding the listing's artist text verbatim (newlines included), alongside the
show's artist associations; the UI renders `display_artists` and turns each artist name it finds inside that text
into a link to the artist's page. This is a schema and display change, and it means the agent must also capture
the verbatim artist text when it extracts a show.

### Event

Event is a parent of Shows, and should be used when it's a music festival or other situations where there are multiple shows, possibly over more than one day or venues. An event page is not high priority, perhaps v2

* Event Name
* Start Day: populated automatically by the earliest show date under Event
* End Day: populated automatically by the last show date under Event
* Shows: it should be associated with more than one Show in order for it to be an Event


### Metro
This is a parent location entity that defines each "tennant" of this sytem. 

It should contain
* Metro name
* Time zone. Every show date and time in the metro is the venue's local clock in this zone: what a listing says ("8 pm") is stored as written, and a source that gives times in another zone (UTC, an offset) is converted into this one.

The metro "page" is the home page for that city. 
We may do a city directory page down the road. 

### Agentic Workflow Requirements (v1)

Agents run once a day (like 4AM local time)

Agents are responsible for discovering and keeping live music show listings current. In v1, agents:

* Read a venue's live music calendar page and identify scheduled shows
* Create new Artist records when an act isn't already in the database
* Keep existing Show records current (added, updated, or removed) as venue calendars change

Agents do **not**, in v1:

* Discover or populate venue metadata (age restriction, alcohol service, venue type, setting, seating) beyond what a human enters
* Discover or populate artist metadata (genre, format, repertoire, members, social links)
* Detect or assemble Events (multi-show festivals)

### Agent Starting Data

At launch, agents are given:

* A single metro area
* A manually curated list of Venues, each with a Live Music Calendar URL

No other venue or artist data is assumed to exist when agent processing begins for a given venue.

### Agent Fetch Behavior

* Every Venue with a Live Music Calendar URL is fetched on a recurring schedule (daily).
* Each fetch captures a point-in-time snapshot of the page content.
* The agent should attempt to traverse or navigate as far into the future as possible. Most live music calendar loads a certain number of days with "load more" or "next" link to navigate to further into the future. 

### Agent Extraction: Fields

Populated automatically from the venue's page, where available:

* Date (required)
* Start Time. If the listing gives no AM/PM, assume PM: live music is overwhelmingly afternoon and evening, and a listing that really is in the morning will say AM. The same applies to an artist's own start time and the End Time.
* Artist(s) performing, including each artist's own start time and performance order. Many listings don't specify the order or the start time of each artist, but in that case make an assumption for an order based on the order in which the artists are listed. 

* End Time: leave blank if unclear
* Admission Advance / Admission Day / Free Admission: if a single admission price is shown on the calendar **without a label**, populate the Admission Day field and leave the Advance field blank. A price shown as an online ticket price ("Buy now $15.24", a ticketing link's price) goes in Admission Advance (Ari, October 10, 2026). Free Admission is true if the listing explicitly says free.  It's ok for neither admission prices nor free admission to be empty. 
* Image (poster link) of the Show. Do not populate Artist image link


Not populated by agents in v1 (inherited-from-venue fields stay blank until a human enters venue-level defaults):

* Age Restriction
* Serves Alcohol
* Setting
* Seating

### Agent Extraction: One Show or Several?

A single listing on a venue's calendar can describe one show with multiple artists, or several distinct shows happening back to back. Treat listings under one time/ticket link as a single multi-artist Show; treat separately timed or separately ticketed listings as distinct Shows. If the listing has multiple start times but has a single link for ticket purchase, then treat it as a single multi-artist Show. 

### Agent Extraction: Accuracy Standards

Set by Ari on October 10, 2026. They apply to every extraction run on the venues used as samples (the evaluation
set), and every run must meet them — an average over runs doesn't count.

* **Date and artists: 100%.** Every show the venue lists is found, with the right date and the right performing
  artists.
* **No made-up shows, ever.** A show that isn't on the venue's page must never be produced.
* **Other fields — start time, end time, admission prices, free admission, image, status: missing is tolerated,
  wrong is not.** If the venue states a value and the agent misses it, up to about 1 time in 10 is acceptable. A
  wrong value — including a value the venue never stated — is never acceptable.
* **Non-music entries: an occasional leak is tolerated.** An open mic, comedy night or similar slipping in about
  once a month per venue is acceptable; more than that is not.
* **When in doubt, include it** (Ari, October 11, 2026). Missing a real show is worse than listing a non-music event:
  missed shows compromise the calendar's core value, while a stray non-music listing is easy for a reader to skip. A
  listing that names a performing artist is treated as a show even if it also mentions karaoke, a party or a series.

### Agent Artist Creation & Matching

* If an artist named on a venue's calendar doesn't already exist, a new Artist record is created automatically, with the name only.
* All other Artist fields (genre, format, repertoire, members) are left blank for a human to fill in later.
* Possible v2 featuer: should an agent-created Artist be visibly marked as unenriched (a "stub" state)? Useful both to invite a contributor to complete it and to help prioritize which records need attention.
* Before creating a new Artist, the system checks whether the named act already exists. Clear matches and clear non-matches resolve automatically; ambiguous matches (similar but not identical names) go through a review step rather than a fixed rule.
* name matching is not scoped to a particular metro area, since artist DB is universal among all metros. 
* Possible v2 feature: how two Artist records that turn out to be the same act get merged after the fact, once a human notices a duplicate. Distinct capability from correcting a single record; nothing else here covers it.

### Agent Handling of Entries in Venue's Live Music Calendar that don't have performing artists

"Karaoke night" "Party" "Open mic" without an identifiable artist will be ignored and not entered into our Shows.  "Hosted by" does not constitute an artist performance in this case. *(Ari, October 11, 2026:)* in a live music show or series, its named hosts **are** acts — an "acoustic night" hosted by musicians is a show with those musicians on it; being "hosted by" someone doesn't make an open mic or comedy night a show.

**Cancelled or postponed listings** (Ari, October 10, 2026) are not shows to display, but they are still extracted,
with their status: the show was most likely extracted on an earlier scan before it was cancelled, and the agent
has to match it to that stored record and update it (see Agent Reconciliation). Only on a venue's very first scan
can a cancelled listing simply be ignored.


### Agent Validation

Every extracted Show is checked before being written to the calendar:

* **Completeness** — required fields are present
* **Plausibility** — dates aren't in the past, times fall in a reasonable range
* **Internal consistency** — for example, Free Admission cannot be true at the same time as an Admission Advance or Admission Day price being set (though the absence of a price does not by itself imply free admission)

If validation fails, the system retries a bounded number of times before giving up and flagging the item for human review. A show that fails validation is never silently dropped — it's always visible somewhere as needing attention.

### Agent Reconciliation (Update, Remove, No-op)

On each fetch, every show currently on the venue's page is compared against what's already stored for that venue:

* A show that matches an existing record and hasn't changed is left alone.
* A show that matches an existing record but has different details (time, lineup) updates that record.
* A show on the page with no existing match is added as new.
* A previously stored show no longer on the page, and falling within the date range that fetch actually covered, is marked removed (not deleted outright — the record and its history are kept).

What counts as "the same show" when a lineup changes between fetches (an opener added, one act drops off). If matching depends on the exact set of artists, a lineup change reads as an old show disappearing and a new one appearing, which is the wrong outcome — it should read as an update to the existing show's lineup. The matching rule relies on date and time as the primary fields.  If, a 8pm show on a given date features a different set of performing artists in the latest scan, then update the Show.  If 8pm show disappears but then 9pm show appears, that's a time change, but then the above rule about making the old show as cancelled and entering a new show applies. 

### Agent Handling of Recurring Listings

A weekly slot ("every Tuesday: this artist") needs no special handling. Each fetch simply extracts whatever is on the page for that date; a recurring slot naturally produces a fresh Show record each time it's observed. No separate "recurring event" concept is required.

### New Venue Submission Workflow

Any user can submit a new venue (name and calendar URL, at minimum). Before it's added to the regular fetch schedule:

* The system attempts to fetch the submitted URL and confirm it actually contains show listings.
* What happens after that attempt: If the agent scan of the live music URL produces credible Shows, automatically add to our DB. If not, we mark the submission as invalid. This also needs its own audit trail entries, consistent with every other agent action, and likely its own review queue.

### Manual & Flagged Re-processing

* An admin can trigger a full run, or re-run a specific prior attempt, on demand.
* Any user can flag a specific show or venue as incorrect; flags accumulate toward triggering a re-fetch and re-extraction of that item, without requiring admin action.
* Every agent action, automatic or manually triggered, is recorded in the audit trail, tied to the specific run that produced it.