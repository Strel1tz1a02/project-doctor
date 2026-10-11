package com.example.slowquery.controller;

import com.example.slowquery.dto.ProviderReleaseVO;
import com.example.slowquery.model.ProviderRelease;
import com.example.slowquery.service.ProviderReleaseService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/providers")
public class ProviderReleaseController {

    private final ProviderReleaseService providerReleaseService;

    public ProviderReleaseController(ProviderReleaseService providerReleaseService) {
        this.providerReleaseService = providerReleaseService;
    }

    @GetMapping("/releases/latest")
    public List<ProviderReleaseVO> latest(@RequestParam String provider,
                                          @RequestParam(defaultValue = "20") int size) {
        return providerReleaseService.recentByProvider(provider, size);
    }

    @GetMapping("/releases")
    public List<ProviderRelease> all() {
        return providerReleaseService.listAll();
    }
}
