package com.example.slowquery.controller;

import com.example.slowquery.dto.BlockDetailVO;
import com.example.slowquery.service.BlockTripService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips")
public class BlockTripController {

    private final BlockTripService blockTripService;

    public BlockTripController(BlockTripService blockTripService) {
        this.blockTripService = blockTripService;
    }

    @GetMapping("/block-details")
    public BlockDetailVO blockDetails(@RequestParam(defaultValue = "200") int size) {
        return blockTripService.blockDetails(size);
    }
}
