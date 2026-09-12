window.dash_clientside = Object.assign({}, window.dash_clientside, {
    lcpKnot: {
        _deleteModeActive: false,
        _rawPlotDiv: null,
        _lastPickTs: 0,

        _deleteModeLive: function (mode) {
            return mode === 'delete';
        },

        _rawPlotlyGraphDiv: function () {
            const root = document.getElementById('lc-processor-graph-working');
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
            if (now - window.dash_clientside.lcpKnot._lastPickTs < 200) {
                return;
            }
            window.dash_clientside.lcpKnot._lastPickTs = now;
            let x0 = null;
            let x1 = null;
            if (plotDiv && plotDiv._fullLayout && plotDiv._fullLayout.xaxis) {
                const range = plotDiv._fullLayout.xaxis.range;
                if (range && range.length === 2) {
                    x0 = range[0];
                    x1 = range[1];
                }
            }
            dash_clientside.set_props('store-lc-processor-knot-pick', {
                data: { x: xy.x, x0: x0, x1: x1, ts: now },
            });
        },

        _ensurePointerListener: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (window.dash_clientside.lcpKnot._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcpKnot._rawPlotDiv = plotDiv;
                delete plotDiv._lcpKnotPointerBound;
            }
            if (plotDiv._lcpKnotPointerBound) {
                return;
            }
            plotDiv._lcpKnotPointerBound = true;
            plotDiv._lcpKnotPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.lcpKnot._deleteModeActive) {
                    return;
                }
                plotDiv._lcpKnotPointerDown = {
                    x: ev.clientX,
                    y: ev.clientY,
                    id: ev.pointerId,
                };
            }, true);

            if (!window.dash_clientside.lcpKnot._docPointerBound) {
                window.dash_clientside.lcpKnot._docPointerBound = true;
                document.addEventListener('pointerup', function (ev) {
                    const livePlot = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                    if (!livePlot) {
                        return;
                    }
                    const down = livePlot._lcpKnotPointerDown;
                    livePlot._lcpKnotPointerDown = null;
                    if (!down || down.id !== ev.pointerId) {
                        return;
                    }
                    if (!window.dash_clientside.lcpKnot._deleteModeActive) {
                        return;
                    }
                    const dx = ev.clientX - down.x;
                    const dy = ev.clientY - down.y;
                    if ((dx * dx + dy * dy) > 64) {
                        return;
                    }
                    const xy = window.dash_clientside.lcpKnot._domEventToPlotXY(
                        livePlot, ev
                    );
                    window.dash_clientside.lcpKnot._emitKnotPick(livePlot, xy);
                }, true);
            }
        },

        _syncPlot: function (mode) {
            const deleteOn = window.dash_clientside.lcpKnot._deleteModeLive(mode);
            window.dash_clientside.lcpKnot._deleteModeActive = deleteOn;
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            if (plotDiv) {
                window.dash_clientside.lcpKnot._ensurePointerListener(plotDiv);
                window.dash_clientside.lcpKnot._setShapesEditable(
                    plotDiv, mode === 'add'
                );
            }
            return deleteOn;
        },

        applyDeleteMode: function (mode) {
            const deleteOn = window.dash_clientside.lcpKnot._syncPlot(mode);
            const attachLater = function () {
                window.dash_clientside.lcpKnot._syncPlot(mode);
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            return deleteOn
                ? 'lcp-graph-shell lcp-delete-mode'
                : 'lcp-graph-shell';
        },

        applyShapes: function (shapes, mode) {
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            if (plotDiv && typeof Plotly !== 'undefined' && Plotly.relayout) {
                const next = Array.isArray(shapes) ? shapes : [];
                Plotly.relayout(plotDiv, {shapes: next}).then(function () {
                    if (mode === 'add') {
                        window.dash_clientside.lcpKnot._setShapesEditable(plotDiv, true);
                    }
                });
            }
            return window.dash_clientside.no_update;
        },

        bindGraph: function (figure, mode) {
            window.dash_clientside.lcpKnot._deleteModeActive =
                window.dash_clientside.lcpKnot._deleteModeLive(mode);
            const attachLater = function () {
                const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpKnot._ensurePointerListener(plotDiv);
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            return window.dash_clientside.no_update;
        },
    },

    lcpExtrema: {
        _mode: 'off',
        _lastPickTs: 0,

        _live: function (mode) {
            return mode === 'add_ext' || mode === 'delete_ext';
        },

        _serialiseAxis: function (value) {
            if (value instanceof Date) {
                return value.getTime();
            }
            return value;
        },

        _emitPick: function (plotDiv, xy) {
            if (!xy || xy.x === null || xy.x === undefined) {
                return;
            }
            if (xy.y === null || xy.y === undefined) {
                return;
            }
            if (typeof dash_clientside.set_props !== 'function') {
                return;
            }
            const now = Date.now();
            const self = window.dash_clientside.lcpExtrema;
            if (now - self._lastPickTs < 200) {
                return;
            }
            self._lastPickTs = now;
            let x0 = null;
            let x1 = null;
            if (plotDiv && plotDiv._fullLayout && plotDiv._fullLayout.xaxis) {
                const range = plotDiv._fullLayout.xaxis.range;
                if (range && range.length === 2) {
                    x0 = self._serialiseAxis(range[0]);
                    x1 = self._serialiseAxis(range[1]);
                }
            }
            dash_clientside.set_props('store-lc-processor-extrema-pick', {
                data: {
                    x: self._serialiseAxis(xy.x),
                    y: xy.y,
                    x0: x0,
                    x1: x1,
                    ts: now,
                },
            });
        },

        _ensurePointerListener: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (window.dash_clientside.lcpExtrema._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcpExtrema._rawPlotDiv = plotDiv;
                delete plotDiv._lcpExtremaPointerBound;
            }
            plotDiv.classList.toggle(
                'lcp-extrema-pick',
                window.dash_clientside.lcpExtrema._live(
                    window.dash_clientside.lcpExtrema._mode
                )
            );
            if (plotDiv._lcpExtremaPointerBound) {
                return;
            }
            plotDiv._lcpExtremaPointerBound = true;
            plotDiv._lcpExtremaPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.lcpExtrema._live(
                    window.dash_clientside.lcpExtrema._mode
                )) {
                    return;
                }
                plotDiv._lcpExtremaPointerDown = {
                    x: ev.clientX,
                    y: ev.clientY,
                    id: ev.pointerId,
                };
            }, true);

            if (!window.dash_clientside.lcpExtrema._docPointerBound) {
                window.dash_clientside.lcpExtrema._docPointerBound = true;
                document.addEventListener('pointerup', function (ev) {
                    const livePlot = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                    if (!livePlot) {
                        return;
                    }
                    const down = livePlot._lcpExtremaPointerDown;
                    livePlot._lcpExtremaPointerDown = null;
                    if (!down || down.id !== ev.pointerId) {
                        return;
                    }
                    if (!window.dash_clientside.lcpExtrema._live(
                        window.dash_clientside.lcpExtrema._mode
                    )) {
                        return;
                    }
                    const dx = ev.clientX - down.x;
                    const dy = ev.clientY - down.y;
                    if ((dx * dx + dy * dy) > 64) {
                        return;
                    }
                    const xy = window.dash_clientside.lcpKnot._domEventToPlotXY(
                        livePlot, ev
                    );
                    window.dash_clientside.lcpExtrema._emitPick(livePlot, xy);
                }, true);
            }
        },

        bindGraph: function (figure, mode) {
            window.dash_clientside.lcpExtrema._mode = mode || 'off';
            const attachLater = function () {
                const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpExtrema._ensurePointerListener(plotDiv);
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            return window.dash_clientside.no_update;
        },
    },

    lcpTilt: {
        _modeOn: false,
        _lastClickTs: 0,
        _suppressRelayout: false,
        _rawPlotDiv: null,

        _plotDiv: function () {
            const root = document.getElementById('lc-processor-graph-residual');
            if (!root) {
                return null;
            }
            const plot = root.querySelector('.js-plotly-plot');
            if (plot && typeof plot.on === 'function') {
                return plot;
            }
            return null;
        },

        _isCoord: function (value) {
            if (value === null || value === undefined) {
                return false;
            }
            if (typeof value === 'number') {
                return isFinite(value);
            }
            if (typeof value === 'string') {
                return value.trim() !== '';
            }
            return value instanceof Date;
        },

        // Same as gpOc._trendLineXBounds: pixel inset, then axis p2d, so a
        // zoomed view still yields 4/5 of the *visible* width.
        _lineXBounds: function (plotDiv) {
            if (!plotDiv || !plotDiv._fullLayout) {
                return null;
            }
            const xaxis = plotDiv._fullLayout.xaxis;
            if (!xaxis || typeof xaxis.p2d !== 'function') {
                return null;
            }
            const width = xaxis._length;
            if (!width || !isFinite(width)) {
                return null;
            }
            const inset = width * 0.1;
            return [xaxis.p2d(inset), xaxis.p2d(width - inset)];
        },

        _previewShape: function (lineStore) {
            return {
                type: 'line',
                xref: 'x',
                yref: 'y',
                x0: lineStore.x0,
                y0: lineStore.y0,
                x1: lineStore.x1,
                y1: lineStore.y1,
                line: {
                    color: '#fd7e14',
                    width: 2,
                },
                editable: true,
                layer: 'above',
                name: 'lcp-tilt-preview-line',
            };
        },

        _stripPreview: function (shapes) {
            if (!shapes || !shapes.length) {
                return [];
            }
            return shapes.filter(function (shape) {
                if (!shape || !shape.name) {
                    return true;
                }
                return !String(shape.name).startsWith('lcp-tilt-');
            });
        },

        _syncPreview: function (plotDiv, lineStore) {
            if (!plotDiv || typeof Plotly === 'undefined') {
                return;
            }
            const existing = plotDiv.layout && plotDiv.layout.shapes
                ? plotDiv.layout.shapes.slice()
                : [];
            const kept = window.dash_clientside.lcpTilt._stripPreview(existing);
            const isCoord = window.dash_clientside.lcpTilt._isCoord;
            if (
                lineStore
                && isCoord(lineStore.x0) && isCoord(lineStore.x1)
                && isCoord(lineStore.y0) && isCoord(lineStore.y1)
            ) {
                kept.push(
                    window.dash_clientside.lcpTilt._previewShape(lineStore)
                );
            }
            window.dash_clientside.lcpTilt._suppressRelayout = true;
            Plotly.relayout(plotDiv, {shapes: kept});
            window.setTimeout(function () {
                window.dash_clientside.lcpTilt._suppressRelayout = false;
            }, 0);
        },

        _syncDragmode: function (plotDiv) {
            if (!plotDiv || typeof Plotly === 'undefined') {
                return;
            }
            // gpOc._syncPrepPlotDragmode: trend mode pans. A click places
            // the line; a drag must not start a zoom box.
            const dragmode = window.dash_clientside.lcpTilt._modeOn
                ? 'pan'
                : 'zoom';
            const current = plotDiv.layout ? plotDiv.layout.dragmode : undefined;
            if (current === dragmode) {
                return;
            }
            Plotly.relayout(plotDiv, {dragmode: dragmode});
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
            return {x: xaxis.p2d(lx), y: yaxis.p2d(ly)};
        },

        _plotClickXY: function (plotDiv, evt) {
            if (!evt) {
                return null;
            }
            if (evt.points && evt.points.length) {
                return {x: evt.points[0].x, y: evt.points[0].y};
            }
            if (evt.xvals && evt.xvals.length) {
                const y = evt.yvals && evt.yvals.length ? evt.yvals[0] : null;
                return {x: evt.xvals[0], y: y};
            }
            if (evt.event) {
                return window.dash_clientside.lcpTilt._domEventToPlotXY(
                    plotDiv, evt.event
                );
            }
            return null;
        },

        _relayoutToStore: function (plotDiv) {
            if (!plotDiv || !plotDiv.layout) {
                return;
            }
            const shapes = plotDiv.layout.shapes;
            if (!shapes || !shapes.length) {
                return;
            }
            let preview = null;
            for (let i = 0; i < shapes.length; i += 1) {
                if (shapes[i] && shapes[i].name === 'lcp-tilt-preview-line') {
                    preview = shapes[i];
                    break;
                }
            }
            if (!preview || typeof dash_clientside.set_props !== 'function') {
                return;
            }
            dash_clientside.set_props('store-lc-processor-tilt-line', {
                data: {
                    x0: preview.x0,
                    y0: preview.y0,
                    x1: preview.x1,
                    y1: preview.y1,
                    ready: true,
                },
            });
        },

        _emitClick: function (xy) {
            if (
                !xy || xy.x === null || xy.x === undefined
                || xy.y === null || xy.y === undefined
            ) {
                return;
            }
            if (typeof dash_clientside.set_props !== 'function') {
                return;
            }
            const now = Date.now();
            if (now - window.dash_clientside.lcpTilt._lastClickTs < 150) {
                return;
            }
            window.dash_clientside.lcpTilt._lastClickTs = now;
            dash_clientside.set_props('store-lc-processor-tilt-click', {
                data: {x: xy.x, y: xy.y, ts: now},
            });
        },

        _ensureListeners: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (!plotDiv._lcpTiltRelayoutBound) {
                plotDiv._lcpTiltRelayoutBound = true;
                plotDiv.on('plotly_relayout', function () {
                    if (!window.dash_clientside.lcpTilt._modeOn) {
                        return;
                    }
                    if (window.dash_clientside.lcpTilt._suppressRelayout) {
                        return;
                    }
                    window.dash_clientside.lcpTilt._relayoutToStore(plotDiv);
                });
            }
            if (plotDiv._lcpTiltPointerBound) {
                return;
            }
            plotDiv._lcpTiltPointerBound = true;
            plotDiv._lcpTiltPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.lcpTilt._modeOn) {
                    return;
                }
                plotDiv._lcpTiltPointerDown = {
                    x: ev.clientX,
                    y: ev.clientY,
                    id: ev.pointerId,
                };
            }, true);

            plotDiv.addEventListener('pointerup', function (ev) {
                if (!window.dash_clientside.lcpTilt._modeOn) {
                    return;
                }
                const down = plotDiv._lcpTiltPointerDown;
                plotDiv._lcpTiltPointerDown = null;
                if (!down || down.id !== ev.pointerId) {
                    return;
                }
                const dx = ev.clientX - down.x;
                const dy = ev.clientY - down.y;
                if ((dx * dx + dy * dy) > 64) {
                    return;
                }
                const xy = window.dash_clientside.lcpTilt._domEventToPlotXY(
                    plotDiv, ev
                );
                window.dash_clientside.lcpTilt._emitClick(xy);
            }, true);

            plotDiv.on('plotly_click', function (evt) {
                if (!window.dash_clientside.lcpTilt._modeOn) {
                    return;
                }
                if (evt && evt.event) {
                    const xy = window.dash_clientside.lcpTilt._domEventToPlotXY(
                        plotDiv, evt.event
                    );
                    if (xy) {
                        window.dash_clientside.lcpTilt._emitClick(xy);
                        return;
                    }
                }
                const xyFallback = window.dash_clientside.lcpTilt._plotClickXY(
                    plotDiv, evt
                );
                window.dash_clientside.lcpTilt._emitClick(xyFallback);
            });
        },

        _bindPlot: function () {
            const plotDiv = window.dash_clientside.lcpTilt._plotDiv();
            if (!plotDiv) {
                return false;
            }
            if (window.dash_clientside.lcpTilt._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcpTilt._rawPlotDiv = plotDiv;
                delete plotDiv._lcpTiltRelayoutBound;
                delete plotDiv._lcpTiltPointerBound;
            }
            window.dash_clientside.lcpTilt._ensureListeners(plotDiv);
            window.dash_clientside.lcpTilt._syncDragmode(plotDiv);
            return true;
        },

        applyMode: function (enabled) {
            const on = enabled === true;
            window.dash_clientside.lcpTilt._modeOn = on;
            const attachLater = function () {
                window.dash_clientside.lcpTilt._bindPlot();
            };
            window.setTimeout(attachLater, 0);
            window.setTimeout(attachLater, 300);
            const plotDiv = window.dash_clientside.lcpTilt._plotDiv();
            if (plotDiv) {
                window.dash_clientside.lcpTilt._syncDragmode(plotDiv);
            }
            if (!on) {
                const plotDivOff = window.dash_clientside.lcpTilt._plotDiv();
                if (plotDivOff) {
                    window.dash_clientside.lcpTilt._syncPreview(plotDivOff, null);
                }
                if (typeof dash_clientside.set_props === 'function') {
                    dash_clientside.set_props('store-lc-processor-tilt-line', {
                        data: null,
                    });
                }
            }
            const plotEl = window.dash_clientside.lcpTilt._plotDiv();
            if (plotEl) {
                plotEl.classList.toggle('lcp-tilt-mode', on);
            }
            return on ? 'lcp-sidebar-btn-row' : 'lcp-sidebar-btn-row d-none';
        },

        bindGraph: function (figure, enabled) {
            window.dash_clientside.lcpTilt._modeOn = enabled === true;
            const attach = function () {
                return window.dash_clientside.lcpTilt._bindPlot();
            };
            if (!attach()) {
                window.setTimeout(attach, 250);
                window.setTimeout(attach, 800);
            }
            return window.dash_clientside.no_update;
        },

        processClick: function (clickPayload, enabled, lineStore) {
            if (enabled !== true || !clickPayload) {
                return window.dash_clientside.no_update;
            }
            if (lineStore && lineStore.ready) {
                return window.dash_clientside.no_update;
            }
            if (clickPayload.y === null || clickPayload.y === undefined) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcpTilt._plotDiv();
            if (!plotDiv) {
                return window.dash_clientside.no_update;
            }
            const xBounds = window.dash_clientside.lcpTilt._lineXBounds(plotDiv);
            if (!xBounds) {
                return window.dash_clientside.no_update;
            }
            const next = {
                x0: xBounds[0],
                y0: clickPayload.y,
                x1: xBounds[1],
                y1: clickPayload.y,
                ready: true,
            };
            window.dash_clientside.lcpTilt._syncPreview(plotDiv, next);
            return next;
        },

        clearLine: function (nClicks) {
            if (!nClicks) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcpTilt._plotDiv();
            if (plotDiv) {
                window.dash_clientside.lcpTilt._syncPreview(plotDiv, null);
            }
            return null;
        },

        restoreLine: function (figure, lineStore, enabled) {
            if (enabled !== true || !lineStore || !lineStore.ready) {
                return window.dash_clientside.no_update;
            }
            const redraw = function () {
                const plotDiv = window.dash_clientside.lcpTilt._plotDiv();
                if (plotDiv && window.dash_clientside.lcpTilt._modeOn) {
                    window.dash_clientside.lcpTilt._syncPreview(plotDiv, lineStore);
                    window.dash_clientside.lcpTilt._syncDragmode(plotDiv);
                }
            };
            window.setTimeout(redraw, 50);
            window.setTimeout(redraw, 400);
            return window.dash_clientside.no_update;
        },
    },
});
