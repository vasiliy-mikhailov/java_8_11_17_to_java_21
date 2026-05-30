package com.example.springbootproject6.security;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;

import com.example.springbootproject6.entity.AppUser;

public class UserDetailsImplementation implements UserDetails {

    private AppUser user;

    public UserDetailsImplementation(AppUser user) {
        this.user = user;
    }

    @Override
    public Collection<? extends GrantedAuthority> getAuthorities() {
        List<SimpleGrantedAuthority> roleList = new ArrayList<>();
        for (String role : user.getStringRoles()) {
            roleList.add(new SimpleGrantedAuthority(role));
        }
        return roleList;
    }

    @Override
    public String getPassword() {
        return user.getPassword();
    }

    @Override
    public String getUsername() {
        return user.getUsername();
    }

}
