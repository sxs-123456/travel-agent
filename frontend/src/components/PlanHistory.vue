<script setup lang="ts">
import type { SavedTrip } from "@/utils/history";
import { downloadTrip } from "@/utils/download";

defineProps<{ items: SavedTrip[] }>();
const emit = defineEmits<{
  (e: "open", item: SavedTrip): void;
  (e: "remove", id: string): void;
}>();

function remove(item: SavedTrip) {
  const title = item.request.city + "\u65c5\u884c\u8ba1\u5212";
  const question = "\u786e\u5b9a\u5220\u9664\u201c" + title + "\u201d\u5417\uff1f";
  if (window.confirm(question)) emit("remove", item.id);
}
</script>

<template>
  <section class="history-page">
    <div class="history-heading">
      <span class="section-kicker">MY TRIPS</span>
      <h1>&#25105;&#30340;&#26053;&#34892;&#35745;&#21010;</h1>
      <p>&#29983;&#25104;&#25104;&#21151;&#30340;&#25915;&#30053;&#20250;&#33258;&#21160;&#20445;&#23384;&#22312;&#24403;&#21069;&#27983;&#35272;&#22120;&#20013;&#65292;&#20043;&#21518;&#21487;&#20197;&#32487;&#32493;&#26597;&#30475;&#25110;&#19979;&#36733;&#12290;</p>
    </div>

    <div v-if="items.length" class="history-grid">
      <article v-for="item in items" :key="item.id" class="history-card">
        <div class="history-card-top">
          <span>{{ item.request.start_date }} &mdash; {{ item.request.end_date }}</span>
          <button type="button" class="history-delete" @click="remove(item)" aria-label="Delete plan">&#21024;&#38500;</button>
        </div>
        <h2>{{ item.request.city }}&#26053;&#34892;&#25915;&#30053;</h2>
        <p class="history-query">&ldquo;{{ item.query }}&rdquo;</p>
        <div class="history-meta">
          <span>{{ item.plan.days.length }} &#22825;</span>
          <span>{{ item.request.travelers }} &#20154;</span>
          <span>{{ item.request.budget_level }}&#39044;&#31639;</span>
        </div>
        <div class="history-actions">
          <button type="button" class="history-open" @click="emit('open', item)">&#26597;&#30475;&#25915;&#30053;</button>
          <button type="button" class="history-download" @click="downloadTrip(item)">&#19979;&#36733;&#25915;&#30053;</button>
        </div>
      </article>
    </div>

    <div v-else class="history-empty">
      <h2>&#36824;&#27809;&#26377;&#20445;&#23384;&#30340;&#25915;&#30053;</h2>
      <p>&#29983;&#25104;&#31532;&#19968;&#20221;&#26053;&#34892;&#35745;&#21010;&#21518;&#65292;&#23427;&#20250;&#33258;&#21160;&#20986;&#29616;&#22312;&#36825;&#37324;&#12290;</p>
      <a href="#/">&#24320;&#22987;&#35268;&#21010;</a>
    </div>
  </section>
</template>
