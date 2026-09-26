<script setup lang="ts">
import { ref } from "vue";
import type { TripPlan } from "@/types/trip";

// 解构保留响应式引用（对象属性解构不会丢失响应性）。
const { plan } = defineProps<{ plan: TripPlan }>();

const emit = defineEmits<{
  (e: "remove-attraction", dayIdx: number, attrIdx: number): void;
  (e: "remove-meal", dayIdx: number, mealIdx: number): void;
  (e: "update-notes", dayIdx: number, value: string): void;
}>();

const failedImages = ref(new Set<string>());
function markImageFailed(url?: string | null) {
  if (!url) return;
  failedImages.value = new Set([...failedImages.value, url]);
}
</script>

<template>
  <div>
    <div
      v-for="(day, di) in plan.days"
      :key="day.day"
      class="tp-card"
      style="margin-bottom: 14px; padding: 16px 18px"
    >
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px">
        <span
          style="
            background: var(--brand);
            color: #fff;
            border-radius: 8px;
            padding: 2px 10px;
            font-weight: 700;
            font-size: 13px;
          "
          >Day {{ day.day }}</span
        >
        <span class="tp-muted">{{ day.date }}</span>
      </div>

      <!-- 景点 -->
      <div v-if="day.attractions.length" style="margin: 6px 0">
        <div class="tp-muted" style="font-size: 12px; margin-bottom: 4px">景点</div>
        <div v-for="(a, ai) in day.attractions" :key="a.name" class="tp-spot">
          <div class="tp-spot-photo">
            <img
              v-if="a.image_url && !failedImages.has(a.image_url)"
              :src="a.image_url"
              class="tp-spot-img"
              alt=""
              loading="lazy"
              @error="markImageFailed(a.image_url)"
            />
            <div v-else class="tp-spot-img tp-spot-img-empty" aria-label="图片暂不可用">景点</div>
            <small v-if="a.image_source && a.image_url && !failedImages.has(a.image_url)" class="tp-spot-image-source">
              {{ a.image_source }}
            </small>
          </div>
          <div class="tp-spot-body">
            <div class="tp-spot-name">
              {{ a.name }}
              <span class="tp-tag">{{ a.recommended_duration }}h</span>
            </div>
            <div class="tp-muted" style="font-size: 12px; margin: 2px 0">
              {{ a.description }}
            </div>
            <div>
              <span v-if="a.ticket_price > 0">
                <span class="tp-price">¥{{ a.ticket_price }}</span>
                <span
                  v-if="a.ticket_price_note"
                  style="font-size: 11px; color: #999; margin-left: 4px"
                  >{{ a.ticket_price_note }}</span
                >
              </span>
              <span class="tp-muted" v-else-if="a.ticket_price_note">门票待确认</span>
              <span class="tp-muted" v-else>免费/现场确认</span>
            </div>
          </div>
          <a-button type="text" danger size="small" @click="emit('remove-attraction', di, ai)">
            移除
          </a-button>
        </div>
      </div>

      <!-- 餐饮 -->
      <div v-if="day.meals.length" style="margin: 6px 0">
        <div class="tp-muted" style="font-size: 12px; margin-bottom: 4px">餐饮</div>
        <div
          v-for="(m, mi) in day.meals"
          :key="m.name"
          style="display: flex; justify-content: space-between; align-items: center; padding: 4px 0"
        >
          <span style="font-size: 13px">
            🍜 {{ m.name }}
            <span class="tp-muted" v-if="m.cuisine">· {{ m.cuisine }}</span>
          </span>
          <span>
            <span v-if="m.price > 0" class="tp-price">¥{{ m.price }}/人</span>
            <span v-else class="tp-muted">人均待确认</span>
            <span
              v-if="m.source_id"
              class="tp-tag"
              style="margin-left: 5px; background: #f6ffed; color: #389e0d"
            >高德 POI</span>
            <span
              v-else-if="m.price_is_estimated"
              class="tp-tag"
              style="margin-left: 5px"
            >模型建议</span>
            <a-button type="text" danger size="small" @click="emit('remove-meal', di, mi)">移除</a-button>
          </span>
        </div>
      </div>

      <!-- 酒店 -->
      <div v-if="day.hotel" style="margin: 6px 0">
        <div class="tp-muted" style="font-size: 12px; margin-bottom: 4px">住宿</div>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-size: 13px">
            🏨 {{ day.hotel.name }}
            <span v-if="day.hotel.level" class="tp-tag">{{ day.hotel.level }}</span>
            <span class="tp-muted">{{ day.hotel.star_rating }}★</span>
          </span>
          <span class="tp-price">
            ¥{{ day.hotel.price_per_night }}/晚 ×{{ plan.budget?.rooms || 1 }}间
            <span
              v-if="day.hotel.price_is_estimated"
              style="font-size: 11px; color: #fa8c16; border: 1px solid #fa8c16; border-radius: 4px; padding: 0 4px; margin-left: 4px"
              >参考价</span
            >
          </span>
        </div>
      </div>

      <!-- 备注编辑 -->
      <a-textarea
        :value="day.notes"
        :rows="2"
        placeholder="路线提示 / 当日备注"
        style="margin-top: 8px"
        @update:value="(v: string | number) => emit('update-notes', di, String(v))"
      />
    </div>
  </div>
</template>
