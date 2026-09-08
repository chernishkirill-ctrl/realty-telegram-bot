import express, { type Express } from "express";
import cors from "cors";
import http from "node:http";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());

const realtyWebAppPort = Number(process.env["REALTY_WEBAPP_PORT"] ?? "8090");
const realtyWebAppPaths = new Map([
  ["/webapp", "/webapp"],
  ["/api/webapp", "/webapp"],
  ["/api/leads", "/api/leads"],
  ["/health", "/health"],
]);

function proxyRealtyWebApp(
  req: express.Request,
  res: express.Response,
  next: express.NextFunction,
) {
  const path = req.url.split("?")[0];
  const targetPath = realtyWebAppPaths.get(path);
  if (!targetPath) {
    next();
    return;
  }
  const query = req.url.includes("?") ? req.url.slice(req.url.indexOf("?")) : "";

  const proxyRequest = http.request(
    {
      hostname: "127.0.0.1",
      port: realtyWebAppPort,
      path: `${targetPath}${query}`,
      method: req.method,
      headers: {
        ...req.headers,
        host: `127.0.0.1:${realtyWebAppPort}`,
      },
    },
    (proxyResponse) => {
      res.status(proxyResponse.statusCode ?? 502);
      for (const [key, value] of Object.entries(proxyResponse.headers)) {
        if (value !== undefined) res.setHeader(key, value);
      }
      proxyResponse.pipe(res);
    },
  );

  proxyRequest.on("error", (error) => {
    logger.error({ err: error }, "Realty WebApp proxy failed");
    if (!res.headersSent) res.status(502).json({ ok: false });
    else res.end();
  });
  req.pipe(proxyRequest);
}

// Must run before express.json() so the POST body can be streamed to Python.
app.use(proxyRealtyWebApp);
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use("/api", router);

export default app;
