/**
 * Crypto Sentinel - Chart Utilities
 * Uses TradingView Lightweight Charts v4
 */

// ---------------------------------------------------------------------------
// Dark theme configuration shared by all charts
// ---------------------------------------------------------------------------
const DARK_THEME = {
    layout: {
        background: { type: 'solid', color: '#161b22' },
        textColor: '#c9d1d9',
    },
    grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
    },
    crosshair: {
        mode: 0, // Normal crosshair
    },
    rightPriceScale: {
        borderColor: '#30363d',
    },
    timeScale: {
        borderColor: '#30363d',
        timeVisible: true,
        secondsVisible: false,
    },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Attach a ResizeObserver to keep the chart sized to its container.
 * @param {HTMLElement} container - The DOM container element
 * @param {Object} chart - Lightweight Charts instance
 */
function observeResize(container, chart) {
    const observer = new ResizeObserver(function handleResize(entries) {
        const entry = entries[0];
        if (!entry) {
            return;
        }
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width: width, height: height });
    });
    observer.observe(container);
    return observer;
}

// ---------------------------------------------------------------------------
// Data Formatting
// ---------------------------------------------------------------------------

/**
 * Format OHLCV array data for lightweight-charts.
 *
 * @param {Array} rawData - [[timestamp_ms, open, high, low, close, volume], ...]
 * @returns {Object} {candles: [...], volumes: [...]}
 */
function formatOHLCV(rawData) {
    if (!Array.isArray(rawData) || rawData.length === 0) {
        return { candles: [], volumes: [] };
    }

    const candles = [];
    const volumes = [];

    for (let i = 0; i < rawData.length; i++) {
        const item = rawData[i];
        const time = Math.floor(item[0] / 1000);
        const open = item[1];
        const high = item[2];
        const low = item[3];
        const close = item[4];
        const volume = item[5];

        candles.push({
            time: time,
            open: open,
            high: high,
            low: low,
            close: close,
        });

        volumes.push({
            time: time,
            value: volume,
            color: close >= open ? '#3fb95080' : '#f8514980',
        });
    }

    return { candles: candles, volumes: volumes };
}

// ---------------------------------------------------------------------------
// Candlestick + Volume Chart
// ---------------------------------------------------------------------------

/**
 * Create a candlestick chart with volume histogram.
 *
 * @param {string} containerId - DOM element ID
 * @param {Array} ohlcvData - [[timestamp_ms, open, high, low, close, volume], ...]
 * @param {Object} options - {height: 500}
 * @returns {Object} {chart, candleSeries, volumeSeries}
 */
function createCandlestickChart(containerId, ohlcvData, options) {
    var opts = options || {};
    var container = document.getElementById(containerId);
    if (!container) {
        throw new Error('Chart container not found: ' + containerId);
    }

    var height = opts.height || 500;

    // 1. Create chart with dark theme
    var chart = LightweightCharts.createChart(container, Object.assign(
        {},
        DARK_THEME,
        {
            width: container.clientWidth,
            height: height,
        }
    ));

    // 2. Add candlestick series
    var candleSeries = chart.addCandlestickSeries({
        upColor: '#3fb950',
        downColor: '#f85149',
        borderUpColor: '#3fb950',
        borderDownColor: '#f85149',
        wickUpColor: '#3fb950',
        wickDownColor: '#f85149',
    });

    // 3. Add volume histogram series (overlay at bottom)
    var volumeSeries = chart.addHistogramSeries({
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    // 4. Format and set data
    var formatted = formatOHLCV(ohlcvData || []);
    candleSeries.setData(formatted.candles);
    volumeSeries.setData(formatted.volumes);

    // 5. Fit content to view
    chart.timeScale().fitContent();

    // 6. Auto-resize with container
    observeResize(container, chart);

    return {
        chart: chart,
        candleSeries: candleSeries,
        volumeSeries: volumeSeries,
    };
}

// ---------------------------------------------------------------------------
// Trade Markers
// ---------------------------------------------------------------------------

/**
 * Add trade markers to a candlestick chart.
 *
 * Each trade produces an entry marker and (if exit data exists) an exit marker.
 * Entry: green arrowUp (long) or red arrowDown (short)
 * Exit:  circle colored by pnl (green = profit, red = loss)
 *
 * @param {Object} candleSeries - The candlestick series
 * @param {Array} trades - [{direction, entry_time, exit_time, entry_price,
 *                           exit_price, pnl}, ...]
 */
function addTradeMarkers(candleSeries, trades) {
    if (!Array.isArray(trades) || trades.length === 0) {
        return;
    }

    var markers = [];

    for (var i = 0; i < trades.length; i++) {
        var trade = trades[i];
        var isLong = (trade.direction || '').toLowerCase() === 'long';

        // Normalise time: accept seconds, milliseconds, or ISO strings
        var entryTime = normaliseTime(trade.entry_time);

        // Entry marker
        markers.push({
            time: entryTime,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#3fb950' : '#f85149',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: (isLong ? 'Long' : 'Short') + ' @ ' + trade.entry_price,
        });

        // Exit marker (only if exit data is present)
        if (trade.exit_time != null && trade.exit_price != null) {
            var exitTime = normaliseTime(trade.exit_time);
            var profitColor = (trade.pnl != null && trade.pnl >= 0)
                ? '#3fb950'
                : '#f85149';
            var pnlText = trade.pnl != null
                ? (trade.pnl >= 0 ? '+' : '') + Number(trade.pnl).toFixed(2)
                : '';

            markers.push({
                time: exitTime,
                position: isLong ? 'aboveBar' : 'belowBar',
                color: profitColor,
                shape: 'circle',
                text: 'Exit ' + pnlText,
            });
        }
    }

    // TradingView requires markers sorted by time ascending
    markers.sort(function (a, b) {
        return a.time - b.time;
    });

    candleSeries.setMarkers(markers);
}

/**
 * Normalise a time value to UTC seconds.
 * Accepts: seconds (number), milliseconds (number > 1e12), or ISO string.
 *
 * @param {number|string} raw - The raw time value
 * @returns {number} UTC seconds
 */
function normaliseTime(raw) {
    if (typeof raw === 'string') {
        return Math.floor(new Date(raw).getTime() / 1000);
    }
    if (typeof raw === 'number') {
        // If the number looks like milliseconds (> Sep 2001 in seconds)
        return raw > 1e12 ? Math.floor(raw / 1000) : Math.floor(raw);
    }
    return 0;
}

// ---------------------------------------------------------------------------
// Equity Curve Chart
// ---------------------------------------------------------------------------

/**
 * Create an equity curve line chart.
 *
 * @param {string} containerId - DOM element ID
 * @param {Array} equityData - [[timestamp_iso, balance], ...] or
 *                             [{time, value}, ...]
 * @param {Object} options - {height: 300, color: '#58a6ff'}
 * @returns {Object} {chart, lineSeries}
 */
function createEquityCurveChart(containerId, equityData, options) {
    var opts = options || {};
    var container = document.getElementById(containerId);
    if (!container) {
        throw new Error('Chart container not found: ' + containerId);
    }

    var height = opts.height || 300;
    var lineColor = opts.color || '#58a6ff';

    // 1. Create chart with dark theme
    var chart = LightweightCharts.createChart(container, Object.assign(
        {},
        DARK_THEME,
        {
            width: container.clientWidth,
            height: height,
        }
    ));

    // 2. Add line series
    var lineSeries = chart.addLineSeries({
        color: lineColor,
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 4,
        priceFormat: {
            type: 'price',
            precision: 2,
            minMove: 0.01,
        },
    });

    // 3. Format data
    var formatted = formatEquityData(equityData || []);

    // 4. Set data
    lineSeries.setData(formatted);

    // 5. Fit content
    chart.timeScale().fitContent();

    // 6. Auto-resize
    observeResize(container, chart);

    return {
        chart: chart,
        lineSeries: lineSeries,
    };
}

/**
 * Format equity data into [{time, value}] for the line series.
 *
 * Accepts:
 *   - [[timestamp_or_iso, balance], ...]
 *   - [{time, value}, ...]
 *
 * @param {Array} data - Raw equity data
 * @returns {Array} [{time: utc_seconds, value: number}, ...]
 */
function formatEquityData(data) {
    if (!Array.isArray(data) || data.length === 0) {
        return [];
    }

    // Detect format from first element
    var first = data[0];

    // Already in {time, value} format
    if (first && typeof first === 'object' && !Array.isArray(first)) {
        return data.map(function (item) {
            return {
                time: normaliseTime(item.time),
                value: Number(item.value),
            };
        });
    }

    // Array-of-arrays: [timestamp_or_iso, balance]
    return data.map(function (item) {
        return {
            time: normaliseTime(item[0]),
            value: Number(item[1]),
        };
    });
}

// ---------------------------------------------------------------------------
// Live Update
// ---------------------------------------------------------------------------

/**
 * Update chart with new candle data (for live polling).
 *
 * Uses .update() which will either update the last bar (if same time) or
 * append a new bar.
 *
 * @param {Object} candleSeries - The candlestick series
 * @param {Object} volumeSeries - The volume histogram series
 * @param {Array} newCandle - [timestamp_ms, open, high, low, close, volume]
 */
function updateChart(candleSeries, volumeSeries, newCandle) {
    if (!Array.isArray(newCandle) || newCandle.length < 6) {
        return;
    }

    var time = Math.floor(newCandle[0] / 1000);
    var open = newCandle[1];
    var high = newCandle[2];
    var low = newCandle[3];
    var close = newCandle[4];
    var volume = newCandle[5];

    candleSeries.update({
        time: time,
        open: open,
        high: high,
        low: low,
        close: close,
    });

    volumeSeries.update({
        time: time,
        value: volume,
        color: close >= open ? '#3fb95080' : '#f8514980',
    });
}
