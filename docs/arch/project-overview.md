# Agentic Live Music Calendar

### Problem Statement

Minneapolis/St. Paul currently has no site that acts as the central live music calendar, where a user can go through and find out what local or touring acts are performing at any given moment.

My idea is to have an agentic central live music calendar, where AI agents will go and read calendars from venues in a given city or metro area and assemble a usable, browsable, discoverable live music calendar.

### Functional Requirements

Calendar Views:

* Lists a live music event which includes the venue, time, act
  * Sometimes time is unclear -- multiple acts for one night, the exact order and time is not described in the calendar listing
* Month, week, day view of calendar
* Filterable by venue or acts
* Searchable for text
* (later) chat based search -- user asks "can you find me an event that features flamenco guitar within 10 miles of my home?"

Community-Editable Entities:

* Allows users to edit information about venue or acts
  * Acts: add social, official websites, members, genre
  * Venue: location, hours, booking info, age (21+?)

Monetization:

* Allow users to donate / contribute toward the hosting costs
* (later) allow acts/venues to promote certain events

Agentic Live Music Listing Discovery:

* There will be a database of venues and their live music calendar page
  * It should include physical address and a link to Google map
* The agents will run once a day and discover live music listings of the venues and make updates to our listings
* Live music listing will be organized by a city or a metro area, such as Minneapolis/St. Paul.
* The focus is on local / indie acts and smaller venues, likes that don't show up on BandsInTown and other sites that cater to national touring acts

### Non-Functional Requirements

I am also using this as a technical learning opportunity on multiple levels:

Must:

* There will be an agent orchestration
  * an agent that reads a live music listing from a venue
  * an agent that validates the quality of agent's interpretation of what it discovers as live music listing -- we need to develop a validation approach for agentic outputs
* We will work with an open-weight AI model
* It will be built on Next.js so that our calendar is discoverable and browseable by search engines
* It will feature a component library
* It will have Python / FastAPI backend
* TBD: hosting - Vercel or AWS
* We need to make the agent workflow auditable -- logging

Optional/Later:

* It will support a multi-tenannt data residency
* The UI and Python layers should run on containers
* Perhaps use a noSQL data store for unstructured data (maybe the venue calendar pages that the agent reads, so that we keep the point-in-time capture of what the venue calendar looked like)


### Implementation Plan

1. Architecting and Foundational Research
   1. Find a style guide for Next.js and FastAPI
   2. Create ERD and data specifications
   3. Determine the initial AI model
   4.
