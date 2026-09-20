import { redirect } from "next/navigation";

/**
 * The console used to live at "/". The marketing landing page now does, served
 * from public/index.html by a beforeFiles rewrite in next.config.mjs, so this
 * route is normally shadowed and never rendered.
 *
 * It is kept as a redirect rather than deleted so that "/" still lands
 * somewhere sensible if that rewrite is ever removed — and so that any old
 * bookmark or hard-coded link to the console root keeps working.
 */
export default function ConsoleRoot() {
  redirect("/overview");
}
