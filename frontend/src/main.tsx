import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DataProvider } from "./DataContext";
import { AssetClass } from "./pages/AssetClass";
import { Dashboard } from "./pages/Dashboard";
import { InstrumentPage } from "./pages/InstrumentPage";
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <BrowserRouter>
      <DataProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="asset/:id" element={<AssetClass />} />
            <Route path="instrument/:id" element={<InstrumentPage />} />
            <Route path="*" element={<p className="muted">Page not found.</p>} />
          </Route>
        </Routes>
      </DataProvider>
    </BrowserRouter>
  </StrictMode>,
);
