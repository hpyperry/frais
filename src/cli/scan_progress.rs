// Rich-style progress bars — matches Python's ui/scan_progress.py.
use crate::plugins::ScannerPlugin;
use indicatif::{MultiProgress, ProgressBar, ProgressStyle};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Thread-safe progress display for the scan phase.
/// Wraps indicatif bars in Arc so they can be shared across threads.
pub struct ScanProgress {
    #[allow(dead_code)]
    multi: MultiProgress, // kept alive for rendering — owns all ProgressBar handles
    bars: BTreeMap<String, ProgressBar>,
    step_labels: BTreeMap<String, Vec<String>>,
    /// Track the last step index we updated the message for.
    /// Matches Python's plugin_steps dict — only rewrite description on step change.
    last_step: Mutex<BTreeMap<String, usize>>,
    /// Per-plugin start times for reporting actual elapsed seconds.
    /// Set at construction; read-only after (no Mutex needed).
    start_times: BTreeMap<String, Instant>,
    /// Per-plugin elapsed seconds, recorded when finish() is called.
    scan_elapsed: Mutex<BTreeMap<String, f64>>,
}

impl ScanProgress {
    /// Create progress bars for the given plugin names.
    /// Returns Arc<Self> for thread-safe sharing via callbacks.
    /// Matches Python's setup_plugin_progress().
    pub fn new(
        selected: &[String],
        all_plugins: &BTreeMap<String, Box<dyn ScannerPlugin>>,
    ) -> Arc<Self> {
        let multi = MultiProgress::new();
        let style = ProgressStyle::with_template(
            "{spinner:.green} {msg:<50} [{wide_bar:.cyan/blue}] {pos}/{len} [{elapsed_precise}]",
        )
        .unwrap()
        .progress_chars("#>-");

        let mut bars = BTreeMap::new();
        let mut step_labels_map = BTreeMap::new();
        let last_step = BTreeMap::new();
        let mut start_times_map = BTreeMap::new();
        let now = Instant::now();

        for name in selected {
            let steps: Vec<String> = all_plugins
                .get(name)
                .map(|p| p.scan_steps().iter().map(|s| s.to_string()).collect())
                .unwrap_or_default();
            let first_step = steps.first().cloned().unwrap_or_default();
            let bar = multi.add(ProgressBar::new(1));
            bar.set_style(style.clone());
            bar.set_position(0);
            bar.set_message(format!("{:<20} {}", name, first_step));
            // Enable steady tick so {elapsed_precise} updates even when no
            // progress callbacks fire (LLM research can take seconds per item).
            // Matches Python Rich's Progress render thread at 10fps (~100ms).
            bar.enable_steady_tick(Duration::from_millis(100));
            bars.insert(name.clone(), bar);
            step_labels_map.insert(name.clone(), steps);
            // Don't pre-set last_step — matches Python's empty plugin_steps dict.
            // When step 0 first arrives, step will != usize::MAX (the fallback),
            // triggering the message update + position reset.
            start_times_map.insert(name.clone(), now);
        }

        Arc::new(ScanProgress {
            multi,
            bars,
            step_labels: step_labels_map,
            last_step: Mutex::new(last_step),
            start_times: start_times_map,
            scan_elapsed: Mutex::new(BTreeMap::new()),
        })
    }

    /// Update progress for a specific plugin step.
    /// Called from on_plugin_progress callback in coordinator::run_scan().
    /// Matches Python's make_progress_callback → _on_progress().
    pub fn update(&self, name: &str, step: usize, done: usize, total: usize) {
        if let Some(bar) = self.bars.get(name) {
            let total_u64 = if total == 0 { 1 } else { total as u64 };
            bar.set_length(total_u64);

            // Only update the message when the step changes — matches Python's
            // `if step != plugin_steps.get(pname):` guard.
            let mut last = self.last_step.lock().unwrap_or_else(|e| e.into_inner());
            if step != *last.get(name).unwrap_or(&usize::MAX) {
                last.insert(name.to_string(), step);
                let step_label = self
                    .step_labels
                    .get(name)
                    .and_then(|steps| steps.get(step))
                    .map(|s| s.as_str())
                    .unwrap_or("");
                bar.set_message(format!("{:<20} {}", name, step_label));
                // Reset position on step transition — matches Python's completed=0
                bar.set_position(0);
            }
            bar.set_position(done as u64);
        }
    }

    /// Mark a plugin as done with final stats.
    /// Called from on_plugin_done callback in coordinator::run_scan().
    /// Matches Python's make_done_callback → _on_plugin_done().
    pub fn finish(&self, name: &str, items: usize, candidates: usize) {
        if let Some(bar) = self.bars.get(name) {
            // Record elapsed time for this plugin
            if let Some(start) = self.start_times.get(name) {
                let elapsed = start.elapsed().as_secs_f64();
                self.scan_elapsed
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .insert(name.to_string(), elapsed);
            }

            let msg = if candidates > 0 {
                format!("{:<20} {} items, {} updates", name, items, candidates)
            } else {
                format!("{:<20} {} items", name, items)
            };
            bar.set_message(msg);
            bar.set_length(1);
            bar.set_position(1);
            bar.finish();
        }
    }

    /// Return the per-plugin elapsed times recorded at finish() time.
    pub fn scan_elapsed_map(&self) -> BTreeMap<String, f64> {
        self.scan_elapsed.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Maximum plugin scan time (= wall-clock duration of the scan phase).
    /// Matches Python's `max(scan_elapsed.values())`.
    pub fn max_scan_time(&self) -> f64 {
        self.scan_elapsed
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .values()
            .copied()
            .fold(0.0f64, f64::max)
    }
}

/// Simple progress bar for the summary phase.
/// Matches Python's summary_progress in _run_summary_phase().
pub struct SummaryBar {
    bar: ProgressBar,
}

impl SummaryBar {
    pub fn new(total: usize) -> Self {
        let style = ProgressStyle::with_template(
            "{spinner:.green} {msg:<50} [{wide_bar:.cyan/blue}] {pos}/{len} [{elapsed_precise}]",
        )
        .unwrap()
        .progress_chars("#>-");

        let bar = ProgressBar::new(total as u64);
        bar.set_style(style);
        bar.set_message("Summaries".to_string());
        bar.enable_steady_tick(Duration::from_millis(100));
        SummaryBar { bar }
    }

    pub fn advance(&self) {
        self.bar.inc(1);
    }

    pub fn finish(&self) {
        self.bar.finish_and_clear();
    }
}
