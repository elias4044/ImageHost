const Charts = {
  line(container, data) {
    const namespace = "http://www.w3.org/2000/svg";
    const width = Math.max(260, container.clientWidth);
    const height = container.clientHeight || 154;
    const left = 30,
      right = 20,
      top = 10,
      bottom = 30;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const maximum = data.yTicks.at(-1);
    const svg = document.createElementNS(namespace, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      data.series[0].values
        .map((value, index) => `${data.labels[index]}: ${value} uploads`)
        .join("; "),
    );
    function node(tag, attributes, text) {
      const item = document.createElementNS(namespace, tag);
      for (const [key, value] of Object.entries(attributes))
        item.setAttribute(key, value);
      if (text !== undefined) item.textContent = text;
      svg.append(item);
      return item;
    }
    const x = (index) => left + (index / (data.labels.length - 1)) * plotWidth;
    const y = (value) => top + plotHeight - (value / maximum) * plotHeight;
    for (const tick of data.yTicks) {
      node("line", {
        x1: left,
        y1: y(tick),
        x2: width - right,
        y2: y(tick),
        class: "grid-line",
      });
      node(
        "text",
        { x: left - 10, y: y(tick) + 4, "text-anchor": "end" },
        data.tickFormat(tick),
      );
    }
    for (const index of data.xAt) {
      node(
        "text",
        {
          x: x(index),
          y: height - 6,
          "text-anchor": index === 0 ? "start" : "middle",
        },
        data.labels[index],
      );
    }
    node("polyline", {
      points: data.series[0].values
        .map((value, index) => `${x(index)},${y(value)}`)
        .join(" "),
      class: "chart-line",
    });
    container.replaceChildren(svg);
  },
};
