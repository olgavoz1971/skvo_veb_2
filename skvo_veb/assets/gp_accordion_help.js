/**
 * Accordion header "?" lives inside the collapse button. Capture-phase
 * handling opens the matching modal via a hidden proxy so the accordion
 * does not toggle.
 */
(function () {
    function helpIndexFromEvent(event) {
        const node = event.target && event.target.closest
            ? event.target.closest(".gp-accordion-help")
            : null;
        if (!node) {
            return null;
        }
        const fromData = node.getAttribute("data-gp-accordion-help");
        if (fromData) {
            return fromData;
        }
        const match = (node.className || "").match(
            /gp-accordion-help--([a-z]+)/
        );
        return match ? match[1] : null;
    }

    function clickHelpProxy(index) {
        const proxy = document.querySelector(
            '[data-gp-help-proxy="' + index + '"], .gp-help-proxy--' + index
        );
        if (proxy) {
            proxy.click();
        }
    }

    document.addEventListener(
        "click",
        function (event) {
            const index = helpIndexFromEvent(event);
            if (!index) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            clickHelpProxy(index);
        },
        true
    );

    document.addEventListener(
        "keydown",
        function (event) {
            if (event.key !== "Enter" && event.key !== " ") {
                return;
            }
            const index = helpIndexFromEvent(event);
            if (!index) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            clickHelpProxy(index);
        },
        true
    );
})();
