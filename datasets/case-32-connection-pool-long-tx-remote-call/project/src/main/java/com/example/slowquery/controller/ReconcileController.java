package com.example.slowquery.controller;

import com.example.slowquery.dto.ReconcileResultVO;
import com.example.slowquery.service.ReconcileService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reconcile")
public class ReconcileController {

    private final ReconcileService reconcileService;

    public ReconcileController(ReconcileService reconcileService) {
        this.reconcileService = reconcileService;
    }

    @GetMapping("/scan")
    public ReconcileResultVO scan(@RequestParam(defaultValue = "20") int batch) {
        return reconcileService.scanAndSettle(batch);
    }
}
