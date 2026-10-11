package com.example.slowquery.service;

import com.example.slowquery.mapper.MemberMapper;
import com.example.slowquery.model.Member;
import org.springframework.stereotype.Service;

@Service
public class MemberService {

    private final MemberMapper memberMapper;

    public MemberService(MemberMapper memberMapper) {
        this.memberMapper = memberMapper;
    }

    public Member findByNo(long memberNo) {
        return memberMapper.findByMemberNo(memberNo);
    }
}
