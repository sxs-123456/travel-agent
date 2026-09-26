import type { SavedTrip } from "./history";

const zh = {
  title: "\u65c5\u884c\u653b\u7565",
  people: "\u4eba",
  budget: "\u9884\u7b97",
  depart: "\u4ece",
  start: "\u51fa\u53d1",
  original: "\u539f\u59cb\u9700\u6c42\uff1a",
  budgetRef: "\u9884\u7b97\u53c2\u8003",
  ticket: "\u95e8\u7968",
  hotel: "\u9152\u5e97",
  meal: "\u9910\u996e",
  transport: "\u4ea4\u901a",
  total: "\u5408\u8ba1",
  day: "\u7b2c",
  dayUnit: "\u5929",
  spots: "\u666f\u70b9",
  suggested: "\u5efa\u8bae",
  hours: "\u5c0f\u65f6",
  ticketAbout: "\u95e8\u7968\u7ea6",
  localFood: "\u5f53\u5730\u7f8e\u98df",
  perPerson: "\u4eba\u5747\u7ea6",
  stay: "\u4f4f\u5bbf",
  perNight: "\u665a",
  tips: "\u63d0\u793a",
  trains: "\u8f66\u6b21\u53c2\u8003",
  noRecommendation: "\u6682\u65e0\u63a8\u8350",
  disclaimer: "\u672c\u653b\u7565\u7531 AI Trip Planner \u751f\u6210\uff0c\u4ec5\u4f9b\u89c4\u5212\u53c2\u8003\uff0c\u7968\u4ef7\u3001\u5f00\u653e\u65f6\u95f4\u548c\u4ea4\u901a\u4fe1\u606f\u8bf7\u4ee5\u5b98\u65b9\u6e20\u9053\u4e3a\u51c6\u3002",
};

function markdownForTrip(item: SavedTrip): string {
  const request = item.request;
  const plan = item.plan;
  const lines = [
    "# " + request.city + zh.title,
    "",
    "> " + request.start_date + " \u81f3 " + request.end_date + " \u00b7 " + request.travelers + " " + zh.people + " \u00b7 " + request.budget_level + zh.budget,
    request.origin_city ? "> " + zh.depart + " " + request.origin_city + " " + zh.start : "",
    "",
    zh.original + item.query,
    "",
  ].filter(Boolean);

  if (plan.budget) {
    lines.push(
      "## " + zh.budgetRef,
      "",
      "- " + zh.ticket + "\uff1a\u00a5" + plan.budget.ticket_total,
      "- " + zh.hotel + "\uff1a\u00a5" + plan.budget.hotel_total,
      "- " + zh.meal + "\uff1a\u00a5" + plan.budget.meal_total,
      "- " + zh.transport + "\uff1a\u00a5" + plan.budget.transport_total,
      "- " + zh.total + "\uff1a\u00a5" + plan.budget.total,
      ""
    );
  }

  for (const day of plan.days) {
    lines.push("## " + zh.day + " " + day.day + " " + zh.dayUnit + " \u00b7 " + day.date, "");
    if (day.attractions.length) {
      lines.push("### " + zh.spots, "");
      day.attractions.forEach((spot) => {
        const price = spot.ticket_price ? "\uff0c" + zh.ticketAbout + " \u00a5" + spot.ticket_price : "";
        lines.push("- **" + spot.name + "**\uff08" + zh.suggested + " " + spot.recommended_duration + " " + zh.hours + price + "\uff09");
        if (spot.description) lines.push("  " + spot.description);
      });
      lines.push("");
    }
    if (day.meals.length) {
      lines.push("### " + zh.meal, "");
      day.meals.forEach((meal) => {
        lines.push("- " + meal.name + " \u00b7 " + (meal.cuisine || zh.localFood) + " \u00b7 " + zh.perPerson + " \u00a5" + meal.price);
      });
      lines.push("");
    }
    if (day.hotel) {
      lines.push("### " + zh.stay, "", "- " + day.hotel.name + " \u00b7 \u7ea6 \u00a5" + day.hotel.price_per_night + "/" + zh.perNight, "");
    }
    if (day.notes) lines.push("### " + zh.tips, "", day.notes, "");
  }

  if (plan.train_info?.length) {
    lines.push("## " + zh.trains, "");
    plan.train_info.forEach((rec) => {
      const train = rec.recommended;
      const detail = train
        ? train.train_no + " " + train.depart_time + "\u2192" + train.arrive_time
        : zh.noRecommendation;
      lines.push("- " + rec.direction + "\uff08" + rec.date + "\uff09\uff1a" + detail);
      if (rec.reason) lines.push("  " + rec.reason);
    });
    lines.push("");
  }

  lines.push("---", zh.disclaimer, "");
  return lines.join("\n");
}

export function downloadTrip(item: SavedTrip) {
  const content = markdownForTrip(item);
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = item.request.city + "-" + item.request.start_date + "-" + zh.title + ".md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
