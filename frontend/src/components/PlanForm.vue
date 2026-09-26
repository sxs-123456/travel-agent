<script setup lang="ts">
import { computed, ref, watch } from "vue";

interface Submission {
  query: string;
  startDate?: string;
  endDate?: string;
}

const props = defineProps<{
  loading?: boolean;
  error?: string;
  missingFields?: string[];
}>();
const emit = defineEmits<{ (e: "submit", value: Submission): void; (e: "edit"): void }>();
const query = ref("");
const startDate = ref("");
const endDate = ref("");
const now = new Date();
const today = [
  now.getFullYear(),
  String(now.getMonth() + 1).padStart(2, "0"),
  String(now.getDate()).padStart(2, "0"),
].join("-");
const datesValid = computed(() => !startDate.value || !endDate.value || endDate.value >= startDate.value);
const canSubmit = computed(() => query.value.trim().length >= 2 && !props.loading && datesValid.value);
const needsDates = computed(() =>
  props.missingFields?.some((field) => field === "start_date" || field === "end_date")
);

watch(query, () => emit("edit"));

function submit() {
  if (!canSubmit.value) return;
  emit("submit", {
    query: query.value.trim(),
    startDate: startDate.value || undefined,
    endDate: endDate.value || undefined,
  });
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="prompt-form" @submit.prevent="submit">
    <label class="sr-only" for="travel-request">&#25551;&#36848;&#20320;&#30340;&#26053;&#34892;&#35745;&#21010;</label>
    <textarea
      id="travel-request"
      v-model="query"
      class="prompt-input"
      rows="3"
      maxlength="1000"
      :disabled="loading"
      @keydown="onKeydown"
    />
    <div class="date-picker-row" :class="{ 'date-picker-needed': needsDates }">
      <label>
        <span>&#20986;&#21457;&#26085;&#26399;</span>
        <input v-model="startDate" type="date" :min="today" :disabled="loading" />
      </label>
      <span class="date-arrow" aria-hidden="true">&rarr;</span>
      <label>
        <span>&#36820;&#31243;&#26085;&#26399;</span>
        <input v-model="endDate" type="date" :min="startDate || today" :disabled="loading" />
      </label>
    </div>
    <p v-if="!datesValid" class="date-error">&#36820;&#31243;&#26085;&#26399;&#19981;&#33021;&#26089;&#20110;&#20986;&#21457;&#26085;&#26399;&#12290;</p>
    <div class="prompt-bottom">
      <p class="prompt-hint">
        &#20889;&#19979;&#30446;&#30340;&#22320;&#65292;&#20063;&#21487;&#20197;&#34917;&#20805;&#20154;&#25968;&#12289;&#39044;&#31639;&#19982;&#21916;&#22909;&#12290;
        <span>&#22238;&#36710;&#29983;&#25104; &middot; Shift + &#22238;&#36710;&#25442;&#34892;</span>
      </p>
      <button class="prompt-submit" type="submit" :disabled="!canSubmit">
        <span v-if="loading" class="prompt-spinner" aria-hidden="true"></span>
        {{ loading ? "\u6b63\u5728\u89c4\u5212\u2026" : "\u751f\u6210\u6211\u7684\u884c\u7a0b" }}
        <span v-if="!loading" aria-hidden="true">&nearr;</span>
      </button>
    </div>
    <div v-if="error" class="prompt-question" role="alert">
      <strong>{{ missingFields?.length ? "\u8fd8\u9700\u8981\u4e00\u70b9\u4fe1\u606f" : "\u6682\u65f6\u65e0\u6cd5\u751f\u6210" }}</strong>
      <p>{{ error }}</p>
    </div>
  </form>
</template>
