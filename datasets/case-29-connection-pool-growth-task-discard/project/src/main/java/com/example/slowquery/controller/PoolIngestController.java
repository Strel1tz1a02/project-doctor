package com.example.slowquery.controller;

import com.example.slowquery.dto.IngestResultVO;
import com.example.slowquery.service.PooledIngestService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/pool")
public class PoolIngestController {

    private final PooledIngestService pooledIngestService;

    public PoolIngestController(PooledIngestService pooledIngestService) {
        this.pooledIngestService = pooledIngestService;
    }

    @GetMapping("/ingest")
    public IngestResultVO ingest(@RequestParam(defaultValue = "16") int workers) {
        return pooledIngestService.ingest(workers);
    }
}
