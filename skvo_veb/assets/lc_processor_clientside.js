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
                if (shapes[i] && shapes[i].name === 'lcp-knot') {
                    update['shapes[' + i + '].editable'] = !!editable;
                }
            }
            if (Object.keys(update).length) {
                Plotly.relayout(plotDiv, update);
            }
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
                const existing = (plotDiv.layout && plotDiv.layout.shapes)
                    ? plotDiv.layout.shapes
                    : [];
                const kept = existing.filter(function (shape) {
                    return shape && shape.name !== 'lcp-knot';
                });
                Plotly.relayout(plotDiv, {shapes: kept.concat(next)}).then(function () {
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

        _anyPickLive: function () {
            const self = window.dash_clientside.lcpExtrema;
            return self._live(self._mode);
        },

        _serialiseAxis: function (value) {
            if (value instanceof Date) {
                return value.getTime();
            }
            return value;
        },

        _emitPick: function (plotDiv, xy, storeId) {
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
            dash_clientside.set_props(storeId, {
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
                window.dash_clientside.lcpExtrema._anyPickLive()
            );
            if (plotDiv._lcpExtremaPointerBound) {
                return;
            }
            plotDiv._lcpExtremaPointerBound = true;
            plotDiv._lcpExtremaPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.lcpExtrema._anyPickLive()) {
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
                    const self = window.dash_clientside.lcpExtrema;
                    if (!self._anyPickLive()) {
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
                    if (self._live(self._mode)) {
                        self._emitPick(
                            livePlot, xy, 'store-lc-processor-extrema-pick'
                        );
                    }
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

    lcpSelect: {
        _perm: [],
        _knotMode: 'off',
        _extremaMode: 'off',
        _intervalControlOn: false,
        _markBandsOn: false,
        _pointsControlOn: false,
        _rawPlotDiv: null,

        _switchOn: function (value) {
            return value === true;
        },

        _selectionBlocked: function () {
            if (!window.dash_clientside.lcpSelect._pointsControlOn) {
                return true;
            }
            const knot = window.dash_clientside.lcpSelect._knotMode;
            const extrema = window.dash_clientside.lcpSelect._extremaMode;
            return (
                knot === 'add'
                || knot === 'delete'
                || extrema === 'add_ext'
                || extrema === 'delete_ext'
                || window.dash_clientside.lcpSelect._intervalControlOn
                || window.dash_clientside.lcpSelect._markBandsOn
            );
        },

        _syncDragmode: function (plotDiv) {
            if (!plotDiv || typeof Plotly === 'undefined' || !Plotly.relayout) {
                return;
            }
            const intervalOn = window.dash_clientside.lcpSelect._intervalControlOn;
            const current = plotDiv.layout ? plotDiv.layout.dragmode : undefined;
            if (!intervalOn && current === 'select') {
                Plotly.relayout(plotDiv, {dragmode: 'zoom'});
            }
        },

        _serialiseAxisValue: function (value) {
            if (value instanceof Date) {
                return value.toISOString();
            }
            return value;
        },

        _permFromValue: function (raw) {
            if (raw === undefined || raw === null || raw === '') {
                return null;
            }
            const nested = Array.isArray(raw) ? raw[0] : raw;
            const n = Number(nested);
            return Number.isFinite(n) ? n : null;
        },

        _permFromEventPoint: function (point, plotDiv) {
            if (!point) {
                return null;
            }
            const fromId = window.dash_clientside.lcpSelect._permFromValue(point.id);
            if (fromId !== null) {
                return fromId;
            }
            const fromCustom = window.dash_clientside.lcpSelect._permFromValue(
                point.customdata
            );
            if (fromCustom !== null) {
                return fromCustom;
            }
            if (!plotDiv || !plotDiv.data) {
                return null;
            }
            const curve = point.curveNumber;
            const idx = (
                point.pointNumber !== undefined && point.pointNumber !== null
                    ? point.pointNumber
                    : point.pointIndex
            );
            const trace = plotDiv.data[curve];
            if (!trace || idx === undefined || idx === null) {
                return null;
            }
            if (Array.isArray(trace.ids) && trace.ids.length) {
                return window.dash_clientside.lcpSelect._permFromValue(trace.ids[idx]);
            }
            return null;
        },

        _selectedPointsForTrace: function (trace, permSet) {
            if (!trace || !Array.isArray(trace.ids) || !trace.ids.length) {
                return [];
            }
            const indices = [];
            for (let i = 0; i < trace.ids.length; i += 1) {
                const perm = window.dash_clientside.lcpSelect._permFromValue(
                    trace.ids[i]
                );
                if (perm !== null && permSet.has(perm)) {
                    indices.push(i);
                }
            }
            return indices;
        },

        _clearLassoOutline: function (plotDiv) {
            if (!plotDiv || typeof Plotly === 'undefined' || !Plotly.relayout) {
                return;
            }
            const update = {selections: []};
            const layout = plotDiv._fullLayout;
            if (
                layout
                && layout.xaxis
                && layout.xaxis.autorange === false
                && layout.xaxis.range
                && layout.xaxis.range.length === 2
            ) {
                update['xaxis.range'] = layout.xaxis.range.slice();
                update['xaxis.autorange'] = false;
            }
            if (
                layout
                && layout.yaxis
                && layout.yaxis.autorange === false
                && layout.yaxis.range
                && layout.yaxis.range.length === 2
            ) {
                update['yaxis.range'] = layout.yaxis.range.slice();
                update['yaxis.autorange'] = false;
            }
            Plotly.relayout(plotDiv, update);
        },

        _paint: function (plotDiv, permList, clearLasso) {
            if (!plotDiv || !plotDiv.data || typeof Plotly === 'undefined') {
                return;
            }
            const permSet = new Set();
            (permList || []).forEach(function (value) {
                const perm = window.dash_clientside.lcpSelect._permFromValue(value);
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            const values = plotDiv.data.map(function (trace) {
                return window.dash_clientside.lcpSelect._selectedPointsForTrace(
                    trace, permSet
                );
            });
            plotDiv.data.forEach(function (trace, index) {
                trace.selectedpoints = values[index];
            });
            if (typeof Plotly.restyle === 'function') {
                Plotly.restyle(plotDiv, {selectedpoints: values});
            } else if (typeof Plotly.redraw === 'function') {
                Plotly.redraw(plotDiv);
            }
            if (clearLasso) {
                window.dash_clientside.lcpSelect._clearLassoOutline(plotDiv);
            }
        },

        _paintSoon: function (plotDiv, permList) {
            const paint = function () {
                window.dash_clientside.lcpSelect._paint(plotDiv, permList, true);
            };
            paint();
            window.setTimeout(paint, 0);
            window.setTimeout(paint, 50);
            window.setTimeout(paint, 80);
        },

        _commitPerm: function (plotDiv, permList) {
            window.dash_clientside.lcpSelect._perm = permList;
            window.dash_clientside.lcpSelect._paintSoon(plotDiv, permList);
            if (typeof dash_clientside.set_props === 'function') {
                dash_clientside.set_props('store-lc-processor-selected-perm', {
                    data: permList,
                });
            }
        },

        _unionEvent: function (plotDiv, evt, currentPerm) {
            const permSet = new Set();
            (currentPerm || []).forEach(function (value) {
                const perm = window.dash_clientside.lcpSelect._permFromValue(value);
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            if (!evt || !evt.points || !evt.points.length) {
                return Array.from(permSet);
            }
            evt.points.forEach(function (point) {
                const perm = window.dash_clientside.lcpSelect._permFromEventPoint(
                    point, plotDiv
                );
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            return Array.from(permSet);
        },

        _onSelectEvent: function (plotDiv, evt) {
            if (window.dash_clientside.lcpSelect._selectionBlocked()) {
                return;
            }
            if (!evt || !evt.points || !evt.points.length) {
                return;
            }
            const next = window.dash_clientside.lcpSelect._unionEvent(
                plotDiv, evt, window.dash_clientside.lcpSelect._perm
            );
            window.dash_clientside.lcpSelect._commitPerm(plotDiv, next);
        },

        _ensureListeners: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (window.dash_clientside.lcpSelect._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcpSelect._rawPlotDiv = plotDiv;
                delete plotDiv._lcpSelectBound;
            }
            if (plotDiv._lcpSelectBound) {
                return;
            }
            plotDiv._lcpSelectBound = true;
            plotDiv.on('plotly_selected', function (evt) {
                const live = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpSelect._onSelectEvent(live || plotDiv, evt);
            });
            plotDiv.on('plotly_click', function (evt) {
                const live = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpSelect._onSelectEvent(live || plotDiv, evt);
            });
        },

        _snapshotZoom: function (plotDiv, timeAxis, domain) {
            const layout = plotDiv && plotDiv._fullLayout;
            if (!layout || !layout.xaxis || !layout.yaxis) {
                return null;
            }
            const serial = window.dash_clientside.lcpSelect._serialiseAxisValue;
            const xa = layout.xaxis;
            const ya = layout.yaxis;
            const next = {
                axis: timeAxis || 'mjd',
                domain: domain || 'flux',
            };
            if (
                xa.autorange === true
                || !xa.range
                || xa.range.length !== 2
            ) {
                next.x_autorange = true;
            } else {
                next.x_autorange = false;
                next.x0 = serial(xa.range[0]);
                next.x1 = serial(xa.range[1]);
            }
            if (
                ya.autorange === true
                || ya.autorange === 'reversed'
                || !ya.range
                || ya.range.length !== 2
            ) {
                next.y_autorange = true;
            } else {
                next.y_autorange = false;
                next.y0 = serial(ya.range[0]);
                next.y1 = serial(ya.range[1]);
            }
            return next;
        },

        _zoomFromRelayout: function (relayoutData, current, timeAxis, domain) {
            const next = Object.assign({}, current || {}, {
                axis: timeAxis || 'mjd',
                domain: domain || 'flux',
            });
            const xAuto = relayoutData['xaxis.autorange'];
            const yAuto = relayoutData['yaxis.autorange'];
            if (xAuto === true) {
                next.x_autorange = true;
                delete next.x0;
                delete next.x1;
            } else if (
                relayoutData['xaxis.range[0]'] !== undefined
                && relayoutData['xaxis.range[1]'] !== undefined
            ) {
                next.x_autorange = false;
                next.x0 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['xaxis.range[0]']
                );
                next.x1 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['xaxis.range[1]']
                );
            } else if (
                Array.isArray(relayoutData['xaxis.range'])
                && relayoutData['xaxis.range'].length === 2
            ) {
                next.x_autorange = false;
                next.x0 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['xaxis.range'][0]
                );
                next.x1 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['xaxis.range'][1]
                );
            }
            if (yAuto === true || yAuto === 'reversed') {
                next.y_autorange = true;
                delete next.y0;
                delete next.y1;
            } else if (
                relayoutData['yaxis.range[0]'] !== undefined
                && relayoutData['yaxis.range[1]'] !== undefined
            ) {
                next.y_autorange = false;
                next.y0 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['yaxis.range[0]']
                );
                next.y1 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['yaxis.range[1]']
                );
            } else if (
                Array.isArray(relayoutData['yaxis.range'])
                && relayoutData['yaxis.range'].length === 2
            ) {
                next.y_autorange = false;
                next.y0 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['yaxis.range'][0]
                );
                next.y1 = window.dash_clientside.lcpSelect._serialiseAxisValue(
                    relayoutData['yaxis.range'][1]
                );
            }
            return next;
        },

        bindGraph: function (
            figure,
            permList,
            knotTool,
            extremaTool,
            intervalControl,
            markBands,
            pointsControl
        ) {
            window.dash_clientside.lcpSelect._knotMode = knotTool || 'off';
            window.dash_clientside.lcpSelect._extremaMode = extremaTool || 'off';
            window.dash_clientside.lcpSelect._intervalControlOn =
                window.dash_clientside.lcpSelect._switchOn(intervalControl);
            window.dash_clientside.lcpSelect._markBandsOn =
                window.dash_clientside.lcpSelect._switchOn(markBands);
            window.dash_clientside.lcpSelect._pointsControlOn =
                window.dash_clientside.lcpSelect._switchOn(pointsControl);
            window.dash_clientside.lcpSelect._perm = Array.isArray(permList)
                ? permList
                : [];
            const attach = function () {
                const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpSelect._ensureListeners(plotDiv);
                window.dash_clientside.lcpSelect._syncDragmode(plotDiv);
                const permForPaint = window.dash_clientside.lcpSelect._pointsControlOn
                    ? window.dash_clientside.lcpSelect._perm
                    : [];
                window.dash_clientside.lcpSelect._paint(
                    plotDiv, permForPaint, false
                );
            };
            window.setTimeout(attach, 0);
            window.setTimeout(attach, 50);
            window.setTimeout(attach, 300);
            return window.dash_clientside.no_update;
        },

        mergeSelection: function (
            selectedData,
            clickData,
            currentPerm,
            knotTool,
            extremaTool,
            intervalControl,
            markBands,
            pointsControl
        ) {
            window.dash_clientside.lcpSelect._knotMode = knotTool || 'off';
            window.dash_clientside.lcpSelect._extremaMode = extremaTool || 'off';
            window.dash_clientside.lcpSelect._intervalControlOn =
                window.dash_clientside.lcpSelect._switchOn(intervalControl);
            window.dash_clientside.lcpSelect._markBandsOn =
                window.dash_clientside.lcpSelect._switchOn(markBands);
            window.dash_clientside.lcpSelect._pointsControlOn =
                window.dash_clientside.lcpSelect._switchOn(pointsControl);
            if (window.dash_clientside.lcpSelect._selectionBlocked()) {
                return window.dash_clientside.no_update;
            }
            const triggered = dash_clientside.callback_context.triggered[0];
            if (!triggered) {
                return window.dash_clientside.no_update;
            }
            const triggerProp = triggered.prop_id.split('.')[1];
            const triggerData = triggerProp === 'selectedData'
                ? selectedData
                : clickData;
            if (!triggerData || !triggerData.points || !triggerData.points.length) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            const base = (window.dash_clientside.lcpSelect._perm || []).concat(
                currentPerm || []
            );
            const next = window.dash_clientside.lcpSelect._unionEvent(
                plotDiv, triggerData, base
            );
            window.dash_clientside.lcpSelect._perm = next;
            window.dash_clientside.lcpSelect._paintSoon(plotDiv, next);
            return next;
        },

        clearSelection: function (nClicks) {
            if (!nClicks) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            window.dash_clientside.lcpSelect._perm = [];
            window.dash_clientside.lcpSelect._paintSoon(plotDiv, []);
            return [];
        },

        captureZoom: function (relayoutData, currentZoom, timeAxis, domain) {
            if (!relayoutData) {
                return window.dash_clientside.no_update;
            }
            const keys = Object.keys(relayoutData);
            const hasAxis = keys.some(function (key) {
                return key.indexOf('xaxis') === 0 || key.indexOf('yaxis') === 0;
            });
            if (!hasAxis) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            const snapshot = window.dash_clientside.lcpSelect._snapshotZoom(
                plotDiv, timeAxis, domain
            );
            if (snapshot) {
                return snapshot;
            }
            return window.dash_clientside.lcpSelect._zoomFromRelayout(
                relayoutData, currentZoom, timeAxis, domain
            );
        },

        invalidateZoom: function (_timeAxis, _domain) {
            return null;
        },
    },

    lcpInterval: {
        _controlOn: false,
        _markOn: false,
        _bands: null,
        _lastClickTs: 0,
        _rawPlotDiv: null,

        _switchOn: function (value) {
            return value === true;
        },

        _plotXToNumber: function (value, axis) {
            if (value === null || value === undefined) {
                return NaN;
            }
            if (typeof value === 'number') {
                return value;
            }
            if (value instanceof Date) {
                return value.getTime();
            }
            const text = String(value);
            if (axis === 'date') {
                const parsed = Date.parse(text);
                return Number.isFinite(parsed) ? parsed : NaN;
            }
            const n = Number(text);
            return Number.isFinite(n) ? n : NaN;
        },

        _idsOverlappingX: function (x, bandsPayload) {
            if (!bandsPayload || !bandsPayload.bands || !bandsPayload.bands.length) {
                return [];
            }
            if (bandsPayload.enabled === false) {
                return [];
            }
            const axis = bandsPayload.axis || 'mjd';
            const toNum = window.dash_clientside.lcpInterval._plotXToNumber;
            const xNum = toNum(x, axis);
            if (!Number.isFinite(xNum)) {
                return [];
            }
            const hits = [];
            for (let b = 0; b < bandsPayload.bands.length; b += 1) {
                const band = bandsPayload.bands[b];
                let b0 = toNum(band.x0, axis);
                let b1 = toNum(band.x1, axis);
                if (!Number.isFinite(b0) || !Number.isFinite(b1)) {
                    continue;
                }
                if (b0 > b1) {
                    const swap = b0;
                    b0 = b1;
                    b1 = swap;
                }
                if (xNum >= b0 && xNum <= b1) {
                    hits.push(String(band.id));
                }
            }
            return hits;
        },

        _bandShapePositions: function (plotDiv) {
            const prefix = 'lcp-int-';
            const positions = {};
            if (!plotDiv) {
                return positions;
            }
            const namedSources = [];
            if (plotDiv.layout && plotDiv.layout.shapes) {
                namedSources.push(plotDiv.layout.shapes);
            }
            if (plotDiv._fullLayout && plotDiv._fullLayout.shapes) {
                namedSources.push(plotDiv._fullLayout.shapes);
            }
            for (let src = 0; src < namedSources.length; src += 1) {
                const shapes = namedSources[src];
                let found = 0;
                for (let s = 0; s < shapes.length; s += 1) {
                    const name = shapes[s] && shapes[s].name;
                    if (typeof name === 'string' && name.indexOf(prefix) === 0) {
                        positions[name.slice(prefix.length)] = s;
                        found += 1;
                    }
                }
                if (found) {
                    return positions;
                }
            }
            return positions;
        },

        _relayoutBandMarks: function (changedIds, markedSet, bandsPayload) {
            const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
            if (!plotDiv || typeof Plotly === 'undefined' || !changedIds.length) {
                return;
            }
            const styles = (bandsPayload && bandsPayload.styles) || null;
            if (!styles || !styles.plain || !styles.marked) {
                return;
            }
            const positions = window.dash_clientside.lcpInterval._bandShapePositions(
                plotDiv
            );
            const update = {};
            for (let i = 0; i < changedIds.length; i += 1) {
                const id = String(changedIds[i]);
                const pos = positions[id];
                if (pos === undefined) {
                    continue;
                }
                const style = markedSet.has(id) ? styles.marked : styles.plain;
                update['shapes[' + pos + '].fillcolor'] = style.fillcolor;
                update['shapes[' + pos + '].opacity'] = style.opacity;
                update['shapes[' + pos + '].line'] = style.line;
            }
            if (Object.keys(update).length) {
                Plotly.relayout(plotDiv, update);
            }
        },

        _emitClick: function (xy) {
            if (!xy || xy.x === null || xy.x === undefined) {
                return;
            }
            if (typeof dash_clientside.set_props !== 'function') {
                return;
            }
            const now = Date.now();
            const self = window.dash_clientside.lcpInterval;
            if (now - self._lastClickTs < 200) {
                return;
            }
            self._lastClickTs = now;
            dash_clientside.set_props('store-lc-processor-interval-click', {
                data: {x: xy.x, ts: now},
            });
        },

        _ensurePointerListener: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            plotDiv.classList.toggle(
                'lcp-interval-mark',
                window.dash_clientside.lcpInterval._markOn
            );
            if (window.dash_clientside.lcpInterval._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcpInterval._rawPlotDiv = plotDiv;
                delete plotDiv._lcpIntervalPointerBound;
            }
            if (plotDiv._lcpIntervalPointerBound) {
                return;
            }
            plotDiv._lcpIntervalPointerBound = true;
            plotDiv._lcpIntervalPointerDown = null;

            plotDiv.addEventListener('pointerdown', function (ev) {
                if (!window.dash_clientside.lcpInterval._markOn) {
                    return;
                }
                plotDiv._lcpIntervalPointerDown = {
                    x: ev.clientX,
                    y: ev.clientY,
                    id: ev.pointerId,
                };
            }, true);

            if (!window.dash_clientside.lcpInterval._docPointerBound) {
                window.dash_clientside.lcpInterval._docPointerBound = true;
                document.addEventListener('pointerup', function (ev) {
                    const livePlot =
                        window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                    if (!livePlot) {
                        return;
                    }
                    const down = livePlot._lcpIntervalPointerDown;
                    livePlot._lcpIntervalPointerDown = null;
                    if (!down || down.id !== ev.pointerId) {
                        return;
                    }
                    if (!window.dash_clientside.lcpInterval._markOn) {
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
                    window.dash_clientside.lcpInterval._emitClick(xy);
                }, true);
            }
        },

        bindGraph: function (figure, intervalControl, markBands, bandsPayload) {
            window.dash_clientside.lcpInterval._controlOn =
                window.dash_clientside.lcpInterval._switchOn(intervalControl);
            window.dash_clientside.lcpInterval._markOn =
                window.dash_clientside.lcpInterval._controlOn
                && window.dash_clientside.lcpInterval._switchOn(markBands);
            window.dash_clientside.lcpInterval._bands = bandsPayload || null;
            const attach = function () {
                const plotDiv = window.dash_clientside.lcpKnot._rawPlotlyGraphDiv();
                window.dash_clientside.lcpInterval._ensurePointerListener(plotDiv);
            };
            window.setTimeout(attach, 0);
            window.setTimeout(attach, 300);
            return window.dash_clientside.no_update;
        },

        toggleMarks: function (clickPayload, marked, bandsPayload, markOn) {
            if (!clickPayload || !window.dash_clientside.lcpInterval._switchOn(markOn)) {
                return window.dash_clientside.no_update;
            }
            const payload = bandsPayload || window.dash_clientside.lcpInterval._bands;
            const hits = window.dash_clientside.lcpInterval._idsOverlappingX(
                clickPayload.x, payload
            );
            if (!hits.length) {
                return window.dash_clientside.no_update;
            }
            const markedSet = new Set(
                (Array.isArray(marked) ? marked : []).map(String)
            );
            const allMarked = hits.every(function (id) {
                return markedSet.has(id);
            });
            for (let k = 0; k < hits.length; k += 1) {
                if (allMarked) {
                    markedSet.delete(hits[k]);
                } else {
                    markedSet.add(hits[k]);
                }
            }
            window.dash_clientside.lcpInterval._relayoutBandMarks(
                hits, markedSet, payload
            );
            return Array.from(markedSet);
        },

        clearMarks: function (nClicks, bandsPayload, marked) {
            if (!nClicks) {
                return window.dash_clientside.no_update;
            }
            const previous = Array.isArray(marked) ? marked.map(String) : [];
            if (previous.length) {
                window.dash_clientside.lcpInterval._relayoutBandMarks(
                    previous,
                    new Set(),
                    bandsPayload || window.dash_clientside.lcpInterval._bands
                );
            }
            return [];
        },

        reflectMarkedCount: function (marked) {
            const count = Array.isArray(marked) ? marked.length : 0;
            return [count === 0, count === 0];
        },
    },
});
