"use client";

// THE CALENDAR'S FILTER HEADER — the only Client Component in the
// calendar, and it holds no results.
//
// "Use client" is on this file because a combobox needs state and event
// handlers; nothing else about the calendar does, so the grid and the show
// blocks stay Server Components. The header never filters anything
// itself: a selection changes the URL, the server page re-renders from
// `searchParams` and streams new data down (arch-initial.md §4, "filter
// and view state: URL search params, not component state"). That is what
// makes a filtered calendar shareable and server-rendered.
//
// Everything it needs arrives as narrow, serialisable props built on the
// server — option lists, and month labels already formatted — so this
// file needs no Temporal and no API client. KEEP IT THAT WAY: import only
// from lib/calendar-href.ts (Temporal-free), never lib/params.ts or
// lib/dates.ts, or the ~36 KB gzipped polyfill ships to every visitor
// (the B3 plan's bundle check, Verification 3, catches it).
//
// No `useSearchParams`: it would need its own <Suspense> boundary, and the
// server has already parsed the URL and passes `filters` down.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useOptimistic, useTransition } from "react";
import {
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxValue,
  useComboboxAnchor,
} from "@repo/ui/components/combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@repo/ui/components/select";
import { withIds,
  buildCalendarHref, 
  type CalendarFilters 
} from "@/lib/calendar-href";

type Option = { id: number; name: string };
type MonthOption = { value: string; label: string };

// The select needs a real value for "no month filter" (the server's
// default four-week window); `null` isn't a selectable item.
const NEXT_FOUR_WEEKS = "next-four-weeks";

export function FilterHeader({
  filters,
  venues,
  artists,
  months,
}: {
  filters: CalendarFilters;
  venues: Option[];
  artists: Option[];
  months: MonthOption[];
}) {
  const router = useRouter();
  // `isPending` is true while the navigation below is in flight, which is
  // what lets the header say "Updating…" without any loading state of its
  // own. `useOptimistic` shows the new selection immediately and falls
  // back to the server's `filters` prop when the navigation lands.
  const [isPending, startTransition] = useTransition();
  const [current, setOptimistic] = useOptimistic(filters);

  function navigate(next: CalendarFilters) {
    // The Client Component never holds the calendar's results. A selection
    // changes the URL; the server page re-renders from `searchParams` and
    // streams new props down. `router.push` runs inside a transition, so
    // `isPending` says a navigation is in flight, and `useOptimistic` shows
    // the new selection at once, reverting to the server's value if the
    // navigation fails or lands elsewhere. `scroll: false` keeps the reader's
    // place instead of jumping to the top. Plan B3-D8: push, not replace, so
    // Back undoes a filter change.
    startTransition(() => {
      setOptimistic(next);
      router.push(buildCalendarHref(next), { scroll: false });
    });
  }

  const isFiltered =
    current.venueIds.length > 0 || current.artistIds.length > 0 || current.month !== null;

  return (
    <div
      aria-busy={isPending}
      className="mt-4 flex flex-col gap-3 md:flex-row md:items-end"
    >
      <div className="min-w-0 flex-1">
        <PickerLabel htmlFor="filter-venues">Venues</PickerLabel>
        <OptionPicker
          inputId="filter-venues"
          placeholder="Any venue"
          options={venues}
          selectedIds={current.venueIds}
          onChange={(ids) => navigate(withIds(current, "venueIds", ids))}
        />
      </div>
      <div className="min-w-0 flex-1">
        <PickerLabel htmlFor="filter-artists">Artists</PickerLabel>
        <OptionPicker
          inputId="filter-artists"
          placeholder="Any artist"
          options={artists}
          selectedIds={current.artistIds}
          onChange={(ids) => navigate(withIds(current, "artistIds", ids))}
        />
      </div>
      <div>
        <PickerLabel htmlFor="filter-month">Month</PickerLabel>
        <Select
          value={current.month ?? NEXT_FOUR_WEEKS}
          items={[{ value: NEXT_FOUR_WEEKS, label: "Next four weeks" }, ...months.map((m) => ({ value: m.value, label: m.label }))]}
          onValueChange={(value) =>
            navigate({ ...current, month: value === NEXT_FOUR_WEEKS ? null : value })
          }
        >
          <SelectTrigger id="filter-month" className="w-full md:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NEXT_FOUR_WEEKS}>Next four weeks</SelectItem>
            {months.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex h-8 items-center gap-3 text-sm">
        {isFiltered && (
          // A plain link, not a handler: "clear" is just the URL with no
          // filters, so it works before hydration too.
          <Link href="/" className="underline">
            Clear filters
          </Link>
        )}
        <span role="status" className="text-muted-foreground">
          {isPending ? "Updating…" : ""}
        </span>
      </div>
    </div>
  );
}

function PickerLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium">
      {children}
    </label>
  );
}

// A multi-select with chips and type-to-filter (requirements: "multi-select
// list with ability to type and filter down the items"). Items are objects
// so the chip can show a name while the URL carries the id; Base UI needs
// to be told how to label one and how to tell two apart.
function OptionPicker({
  inputId,
  placeholder,
  options,
  selectedIds,
  onChange,
}: {
  inputId: string;
  placeholder: string;
  options: Option[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}) {
  const anchor = useComboboxAnchor();
  const selected = options.filter((o) => selectedIds.includes(o.id));

  return (
    <Combobox
      multiple
      items={options}
      value={selected}
      itemToStringLabel={(o: Option) => o.name}
      isItemEqualToValue={(a: Option, b: Option) => a.id === b.id}
      onValueChange={(next: Option[]) => onChange(next.map((o) => o.id))}
    >
      <ComboboxChips ref={anchor}>
        <ComboboxValue>
          {(values: Option[]) => (
            <>
              {values.map((o) => (
                <ComboboxChip key={o.id}>{o.name}</ComboboxChip>
              ))}
              <ComboboxChipsInput
                id={inputId}
                placeholder={values.length > 0 ? "" : placeholder}
              />
            </>
          )}
        </ComboboxValue>
      </ComboboxChips>
      <ComboboxContent anchor={anchor}>
        <ComboboxEmpty>No matches</ComboboxEmpty>
        <ComboboxList>
          {(o: Option) => (
            <ComboboxItem key={o.id} value={o}>
              {o.name}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
