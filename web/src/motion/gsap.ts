import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { TextPlugin } from "gsap/TextPlugin";

/**
 * Plugins are registered once, here. This file is only ever imported from the lazy motion chunk, so
 * the animation library is never part of the first load; the public pages are complete without it.
 * (GSAP is free for commercial use, including these plugins, since 3.13.)
 */
gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText, DrawSVGPlugin, MotionPathPlugin, TextPlugin);

export { gsap, ScrollTrigger, SplitText };
