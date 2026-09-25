import { createApp } from "vue";
import Button from "ant-design-vue/es/button";
import DatePicker from "ant-design-vue/es/date-picker";
import Form from "ant-design-vue/es/form";
import Input from "ant-design-vue/es/input";
import InputNumber from "ant-design-vue/es/input-number";
import Progress from "ant-design-vue/es/progress";
import Select from "ant-design-vue/es/select";
import "ant-design-vue/dist/reset.css";
import App from "./App.vue";
import "./styles/global.css";

createApp(App)
  .use(Button)
  .use(DatePicker)
  .use(Form)
  .use(Input)
  .use(InputNumber)
  .use(Progress)
  .use(Select)
  .mount("#app");
