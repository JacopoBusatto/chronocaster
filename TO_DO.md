**Bugs**
1. The FILTER_LABEL starts in part on the fixed bar that shows when casting should refer to the next filter that triggers, wether it is a D filter of U filter
2. The next phase button in the fixed bar is not triggering the next phase advance, only the red one does that

**Fixed**
1. after the start, I noticed that the recovered mark on the predicted path plot is before the end of the U-1 filter (with default values) — propagation loop now only chains T2 stops from bottom-leave; Recovered event updated accordingly
2. Ordering in the plot with the option for the filter clock that resets at the end of the previous filtering phase is is wrong: it shows that the end of the last filtering phase comes later than the return to surface phase
2. Casting loops between phases end of filtering/ascending to surface/retrieving to the deck both in plot and in the buttons 
3. Missing waiting phase for T2-2 in the phases list and in the plot (the CSV is correct)
4. Add settable time for the deploy to surface phase
5. start cast tracker: T2 preset default value doesn't match the suggested one
6. When it's filtering, there is the indicator that shows that I'm late of X minutes, with X increasing as we filter, but since we are in the filtering phase, if the expected phase in that moment is the same filtering phase we shouldn't be more late than when we started 

**To add**

**Added**
1. advanced settings: homing time (default 30 s) that adds up to the filtering time
2. advanced settings: filtering activation buffer (default 10 s) that adds up to the filtering time
3. advanced settings: time at the bottoms (default 5 s)
4. Specific time delays for each filters, not a general one
5. 

**Check**

**Checked**
1. check the calculation of the required speed: once I'm ascending/descending it should be fixed until reached the target depth
2. check lateness colors

**Renaming**
-

**Aesthetic**

**Aesthetic done**
1. Move the start bottom inside and on the right side of the current phase blue panel and make it smaller — pre-cast uses [4,1] columns; active cast next-phase button is in a [4,1] column beside the banner
2. next phase button can be like "next phase" instead of done — now "➡️ Next phase" / "🏁 Complete"
3. Move the pre-cast reference before the start button — done
4. Start button should be smaller and less verbose.
It can have just the play icone for the start of the cast and then another symbole for the next phase button
Since there is the blue box that describes the current phase, there's no need on informations on the red button.
5. The current phase blue panel is showing T+ (that should be the time from the start) and the depth of the phase. these are informations that are written somewhere near, so there's no need to have those in the panel
6. The current phase panel and the next phase button should be right over the plot I believe
7. After the start of the cast, is it possible to have panel that contains
- current phase name
- next phase buttons
- cast time
- time to next phase
- FILTER_LABEL timer fires at (that should be renamed as FILTER_LABEL starts in) 
that, once the cast started, it is fixed on the screen and the rest of the page is free to scroll up and down.
8. I would remove the grey ovans that now are below the current Time to next phase clock and FILTER_LABEL timer fires in 
9. Put the next phase button in the fixed upper panel, on the left
