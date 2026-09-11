window.dash_clientside = Object.assign({}, window.dash_clientside, {
    detrendKnot: {
        _deleteModeActive: false,
        _rawPlotDiv: null,
        _lastPickTs: 0,

        _deleteModeLive: function (mode) {
            return mode === 'delete';
        },

        _rawPlotlyGraphDiv: function () {
            const root = document.getElementById('detrend-graph-raw');
            if (!root) {
                return null;
            }
            const plot = root.querySelector('.js-plotly-plot');
            if (plot && typeof plot.on === 'function') {
                return plot;
            }
            return null;
        },

        _domEventToPlotXY: function (plotDiv, domEvent) {
            if (!plotDiv || !plotDiv._fullLayout || !domEvent) {
                return null;
            }
            const xaxis = plotDiv._fullLayout.xaxis;
            const yaxis = plotDiv._fullLayout.yaxis;
            if (
                !xaxis || typeof xaxis.p2d !== 'function'
                || !yaxis || typeof yaxis.p2d !== 'function'
            ) {
                return null;
            }
            const bbox = plotDiv.getBoundingClientRect();
            const lx = domEvent.clientX - bbox.left - xaxis._offset;
            const ly = domEvent.clientY - bbox.top - yaxis._offset;
            if (
                !isFinite(xaxis._length) || !isFinite(yaxis._length)
                || lx < 0 || ly < 0
                || lx > xaxis._length || ly > yaxis._length
            ) {
                return null;
            }
            return { x: xaxis.p2d(lx), y: yaxis.p2d(ly) };
        },

        _setShapesEditable: function (plotDiv, editable) {
            if (!plotDiv || typeof Plotly === 'undefined' || !plotDiv.layout) {
                return;
            }
            const shapes = plotDiv.layout.shapes;
            if (!shapes || !shapes.length) {
                return;
            }
            const update = {};
            for (let i = 0; i < shapes.length; i += 1) {
                update['shapes[' + i + '].editable'] = !!editable;
            }
            Plotly.relayout(plotDiv, update);
        },

        _emitKnotPick: function (plotDiv, xy) {
            if (!xy || xy.x === null || xy.x === undefined) {
                return;
            }
            if (typeof dash_clientside.set_props !== 'function') {
                return;
            }
            const now = Date.now();
            if (now - window.dash_clientside.detrendKnot._lastPickTs < 200) {
                return;
            }
            window.dash_clientside.detrendKnot._lastPickTs = now;
            let x0 = null;
            let x1 = null;
            if (plotDiv && plotDiv._fullLayout && plotDiv._fullLayout.xaxis) {
                const range = plotDiv._fullLayout.xaxis.range;
                if (range && range.length === 2) {
                    x0 = range[0];
                    x1 = range[1];
                }
            }
            dash_clientside.set_props('detrend-store-knot-pick', {
                data: { x: xy.x, x0: x0, x1: x1, ts: now },
            });
        },

        _ensurePointerListener: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (window.dash_clientside.detrendKnot._rawPlotDiv !== plotDiv) {
                window.dash_clientside.detrendKnot._rawPlotDiv = plotDiv;
                delete plotDiv._detrendKnotPointerBound;
            }
            if (plotDiv._detrendKnotPointerBound) {
                return;
            }
            plotDiv._detrendKnotPointerBound = true;
            plotDiv._detrendKnotPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.detrendKnot._deleteModeActive) {
                    return;
                }
                plotDiv._detrendKnotPointerDown = {
                    x: ev.clientX,
                    y: ev.clientY,
                    id: ev.pointerId,
                };
            }, true);

            if (!window.dash_clientside.detrendKnot._docPointerBound) {
                window.dash_clientside.detrendKnot._docPointerBound = true;
                document.addEventListener('pointerup', function (ev) {
                    const livePlot = window.dash_clientside.detrendKnot._rawPlotlyGraphDiv();
                    if (!livePlot) {
                        return;
                    }
                    const down = livePlot._detrendKnotPointerDown;
                    livePlot._detrendKnotPointerDown = null;
                    if (!down || down.id !== ev.pointerId) {
                        return;
                    }
                    if (!window.dash_clientside.detrendKnot._deleteModeActive) {
                        return;
                    }
                    const dx = ev.clientX - down.x;
                    const dy = ev.clientY - down.y;
                    if ((dx * dx + dy * dy) > 64) {
                        return;
                    }
                    const xy = window.dash_clientside.detrendKnot._domEventToPlotXY(
                        livePlot, ev
                    );
                    window.dash_clientside.detrendKnot._emitKnotPick(livePlot, xy);
                }, true);
            }
        },

        _syncPlot: function (mode) {
            const deleteOn = window.dash_clientside.detrendKnot._deleteModeLive(mode);
            window.dash_clientside.detrendKnot._deleteModeActive = deleteOn;
            const plotDiv = window.dash_clientside.detrendKnot._rawPlotlyGraphDiv();
            if (plotDiv) {
                window.dash_clientside.detrendKnot._ensurePointerListener(plotDiv);
                window.dash_clientside.detrendKnot._setShapesEditable(
                    plotDiv, mode === 'add'
                );
            }
            return deleteOn;
        },

        applyDeleteMode: function (mode) {
            const deleteOn = window.dash_clientside.detrendKnot._syncPlot(mode);
            const attachLater = function () {
                window.dash_clientside.detrendKnot._syncPlot(mode);
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            return deleteOn
                ? 'detrend-graph-shell detrend-delete-mode'
                : 'detrend-graph-shell';
        },

        bindGraph: function (figure, mode) {
            window.dash_clientside.detrendKnot._deleteModeActive =
                window.dash_clientside.detrendKnot._deleteModeLive(mode);
            const attachLater = function () {
                const plotDiv = window.dash_clientside.detrendKnot._rawPlotlyGraphDiv();
                window.dash_clientside.detrendKnot._ensurePointerListener(plotDiv);
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            return window.dash_clientside.no_update;
        },
    },
});
