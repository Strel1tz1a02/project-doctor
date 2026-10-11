package com.example.slowquery.controller;

import com.example.slowquery.model.Member;
import com.example.slowquery.service.MemberService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/members")
public class MemberController {

    private final MemberService memberService;

    public MemberController(MemberService memberService) {
        this.memberService = memberService;
    }

    @GetMapping("/by-no")
    public Member byNo(@RequestParam(defaultValue = "100000001") long memberNo) {
        return memberService.findByNo(memberNo);
    }
}
