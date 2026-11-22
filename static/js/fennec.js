import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

const mouths = {
  rest:  [0, 0, 0, .069, 0,    -.070],
  open:  [1, 0, 0, .066, .028, -.087],
  round: [0, 1, 0, .038, .023, -.083],
  wide:  [0, 0, 1, .082, .015, -.077],
};

// L’intérieur de la bouche suit la surface déformée du museau.
function shadeMouth(material, aperture) {
  material.onBeforeCompile = (shader) => {
    shader.uniforms.fennecMouth = aperture;
    shader.vertexShader = "varying vec3 fennecPosition;\n" + shader.vertexShader.replace(
      "#include <morphtarget_vertex>", "#include <morphtarget_vertex>\nfennecPosition = transformed;"
    );
    shader.fragmentShader = "varying vec3 fennecPosition;\nuniform vec3 fennecMouth;\n" +
      shader.fragmentShader.replace("#include <color_fragment>", `
        #include <color_fragment>
        float u = (fennecPosition.z + .083) / fennecMouth.x;
        float v = (fennecPosition.y - fennecMouth.z + .009 * u * u) / max(fennecMouth.y, .001);
        float inner = (1.0 - smoothstep(.75, 1.02, u*u + v*v))
                    * smoothstep(.235, .265, fennecPosition.x)
                    * smoothstep(.001, .009, fennecMouth.y);
        float tongue = (1.0 - smoothstep(.32, 1.0, abs(u)))
                     * (1.0 - smoothstep(.14, .39, abs(v + .60)));
        vec3 cavity = mix(vec3(.024, .008, .009), vec3(.22, .065, .055), tongue);
        diffuseColor.rgb = mix(diffuseColor.rgb, cavity, inner);
      `);
  };
}

export async function createFennec(stage) {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  renderer.domElement.setAttribute("aria-hidden", "true");

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(26, 1, .1, 10);
  scene.add(new THREE.HemisphereLight(0xfff4e8, 0xafa18d, 2.0));
  const key = new THREE.DirectionalLight(0xffe6ca, 2.2);
  key.position.set(3, 4, 1.5);
  const fill = new THREE.DirectionalLight(0xe9f1ff, 1.1);
  fill.position.set(1, 2, -3);
  scene.add(key, fill);

  let fennec;
  try {
    ({ scene: fennec } = await new GLTFLoader().loadAsync(stage.dataset.model));
  } catch (error) {
    renderer.dispose();
    throw error;
  }
  const heading = new THREE.Group();
  heading.add(fennec);
  scene.add(heading);
  const aperture = { value: new THREE.Vector3(...mouths.rest.slice(3)) };
  const animated = [];
  fennec.traverse((object) => {
    if (!object.isMesh) return;
    shadeMouth(object.material, aperture);
    animated.push(object);
  });
  const preferredMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let last = 0;
  let elapsed = 0;
  let travel;
  let travelDuration = 0;
  let hovering = false;
  let hoverTime = 0;
  let attention = 0;
  let nod = 0;
  let emotion = "";
  let emotionAge = 0;
  let listening = 0;
  let target = mouths.rest;
  let mouth = mouths.rest.slice();

  function resize() {
    const { clientWidth: width, clientHeight: height } = stage;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const distance = Math.max(2.65, 2.25 / camera.aspect);
    camera.position.set(distance, .065, .24);
    camera.lookAt(0, -.01, 0);
    camera.updateProjectionMatrix();
  }

  function draw(now) {
    const dt = last ? Math.min(.05, (now - last) / 1000) : 1 / 60;
    last = now;
    elapsed += dt;
    const animate = !preferredMotion.matches;
    const thinking = animate && stage.dataset.thinking === "true";
    const nextEmotion = animate ? stage.dataset.emotion || "" : "";
    emotionAge = nextEmotion === emotion ? emotionAge + dt : 0;
    emotion = nextEmotion;
    listening = THREE.MathUtils.damp(listening, animate && stage.dataset.listening === "true" ? 1 : 0, 12, dt);
    const gesture = Math.sin(Math.PI * Math.min(1, emotionAge / 1.3));
    const pointing = emotion === "point" ? gesture : 0;
    const concern = emotion === "concern" ? gesture : 0;
    const approval = emotion === "success" ? gesture * Math.sin(emotionAge * 12) : 0;
    const speaking = target !== mouths.rest;
    // Les appuis et la direction suivent la même horloge que le déplacement à l’écran.
    const time = travel?.currentTime ?? 0;
    const progress = travelDuration ? time / travelDuration : 0;
    const running = animate && travel ? THREE.MathUtils.smoothstep(progress, 0, .16) *
      (1 - THREE.MathUtils.smoothstep(progress, .74, .98)) : 0;
    const stride = Math.cos(time * .027);
    hoverTime = animate && hovering && !travel ? hoverTime + dt : 0;
    attention = THREE.MathUtils.damp(attention, hoverTime > .10 ? 1 : 0, 10, dt);
    const greeting = Math.sin(Math.PI * THREE.MathUtils.clamp((hoverTime - .12) / .55, 0, 1));
    nod = THREE.MathUtils.damp(nod, greeting, 18, dt);
    const blend = 1 - Math.exp(-24 * dt);
    mouth = mouth.map((value, i) => THREE.MathUtils.lerp(value, target[i], blend));
    aperture.value.set(mouth[3], mouth[4], mouth[5]);
    const breath = animate ? .45 + .40 * Math.sin(elapsed * 2.3) : 0;
    const earTwitch = animate ? Math.max(0, Math.sin(elapsed * 1.7)) ** 24 * .65 : 0;
    const tilt = animate ? (.35 + .25 * Math.sin(elapsed * 1.5) + (thinking ? .36 : 0)) : 0;
    const turn = animate ? .085 * Math.sin(elapsed * 1.1) + (speaking ? .035 * Math.sin(elapsed * 3.0) : 0) : 0;
    heading.rotation.y = THREE.MathUtils.damp(heading.rotation.y,
      THREE.MathUtils.lerp(turn - .15 * attention - .52 * pointing, 1.19, running), 17, dt);
    fennec.rotation.z = running * (-.10 + .055 * stride) - .09 * nod - .12 * approval - .05 * concern;
    fennec.position.y = running * (.018 + .038 * stride * stride) + .04 * nod;
    for (const mesh of animated) {
      const i = mesh.morphTargetDictionary;
      const w = mesh.morphTargetInfluences;
      w[i.mouth_open] = mouth[0];
      w[i.mouth_round] = mouth[1];
      w[i.mouth_wide] = mouth[2];
      w[i.breath] = breath * (1 - running);
      w[i.ears] = earTwitch * (1 - Math.max(attention, listening)) - .48 * attention + .42 * nod - .55 * listening + .78 * concern;
      w[i.head_tilt] = tilt + .48 * attention + .55 * listening;
      w[i.run_stance] = running;
      w[i.stride_a] = running * Math.max(0, stride);
      w[i.stride_b] = running * Math.max(0, -stride);
    }
    renderer.render(scene, camera);
    requestAnimationFrame(draw);
  }

  stage.append(renderer.domElement);
  resize();
  renderer.render(scene, camera);
  if (!renderer.getContext().isContextLost()) stage.classList.add("chat-fennec-ready");
  new ResizeObserver(resize).observe(stage);
  renderer.domElement.addEventListener("webglcontextlost", () => stage.classList.remove("chat-fennec-ready"));
  renderer.domElement.addEventListener("webglcontextrestored", () => stage.classList.add("chat-fennec-ready"));
  requestAnimationFrame(draw);

  return {
    setMouth(shape) { target = mouths[shape] || mouths.rest; },
    setHover(active) { hovering = active; },
    setTravel(animation) {
      travel = animation;
      travelDuration = animation?.effect.getTiming().duration ?? 0;
    },
  };
}
